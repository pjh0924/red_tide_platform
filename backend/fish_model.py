"""어종 출현 모델 통합 인터페이스.

현재 구현: heuristic (환경 변수 가우시안 + 월별 가중치).
미래 교체: KOSIS 어획 라벨 + KOEM/KMA features 로 supervised ML 학습 후 같은 인터페이스로 swap.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from data_pipeline.features import build_features, load_koem_measurements
from data_pipeline.regions import REGIONS
from fish_pipeline.heuristic import (all_species_probabilities, fish_risk_color,
                                      fish_risk_level, seasonal_curve)
from fish_pipeline.species import SPECIES, get_species

# 모델 등록 정보 (UI 노출용)
MODEL_INFO = {
    "kind": "heuristic",
    "version": "0.1.0",
    "description": "환경 변수 가우시안 적합도 + 월별 회유 가중치. "
                   "KOSIS 어획 라벨 확보 시 supervised ML 로 자동 교체.",
}


def latest_env_for_region(region: str, features: pd.DataFrame,
                           measurements: pd.DataFrame | None = None) -> dict:
    """region 의 가장 최근 (sst, salinity, month) 한 점."""
    today = pd.Timestamp(datetime.now().date())
    sub = features[(features["region"] == region) & (features["date"] <= today)].tail(1)
    if sub.empty:
        return {"sst": None, "salinity": None, "month": today.month, "as_of": None}
    row = sub.iloc[0]
    return {
        "sst": float(row["sst"]) if pd.notna(row.get("sst")) else None,
        "salinity": float(row["salinity"]) if pd.notna(row.get("salinity")) else None,
        "month": int(row["date"].month),
        "as_of": row["date"].strftime("%Y-%m-%d"),
    }


def predict_now(region: str, features: pd.DataFrame) -> dict:
    """region 의 현재 시점 어종별 출현 확률."""
    env = latest_env_for_region(region, features)
    if env["sst"] is None:
        return {"region": region, "as_of": env["as_of"], "env": env, "species": []}
    probs = all_species_probabilities(env["sst"], env["salinity"], env["month"])
    species_out = []
    for sp in SPECIES:
        p = probs[sp["id"]]
        species_out.append({
            "id": sp["id"], "ko": sp["ko"], "sci": sp["sci"], "habitat": sp["habitat"],
            "color": sp["color"],
            "probability": round(p, 4),
            "level": fish_risk_level(p),
            "level_color": fish_risk_color(p),
        })
    species_out.sort(key=lambda x: x["probability"], reverse=True)
    return {
        "region": region, "as_of": env["as_of"], "env": env, "species": species_out,
    }


def forecast(region: str, features: pd.DataFrame, days: int = 7) -> dict:
    """향후 N일 어종별 출현 확률.
    환경 features 가 일별로 변하지 않으면 (KOEM 분기 측정), 결과도 거의 일정.
    실시간 환경 (ASOS) 통합 후 차별화 강화 예정.
    """
    today = pd.Timestamp(datetime.now().date())
    end = today + timedelta(days=days)
    sub = features[(features["region"] == region) &
                   (features["date"] >= today) & (features["date"] <= end)]
    if sub.empty:
        # 미래 features 가 없으면 가장 최근 값으로 대체
        env = latest_env_for_region(region, features)
        future_dates = pd.date_range(today, end, freq="D")
        rows = []
        for d in future_dates:
            probs = all_species_probabilities(env["sst"], env["salinity"], d.month)
            rows.append({"date": d.strftime("%Y-%m-%d"), "probabilities": probs})
        return {"region": region, "horizon_days": days, "forecast": rows,
                "env_source": "latest_known"}
    rows = []
    for _, r in sub.iterrows():
        probs = all_species_probabilities(
            float(r["sst"]) if pd.notna(r.get("sst")) else None,
            float(r["salinity"]) if pd.notna(r.get("salinity")) else None,
            int(r["date"].month),
        )
        rows.append({"date": r["date"].strftime("%Y-%m-%d"),
                     "probabilities": probs})
    return {"region": region, "horizon_days": days, "forecast": rows,
            "env_source": "features"}


def seasonal_for_species(region: str, species_id: str,
                          features: pd.DataFrame) -> dict:
    """region 의 어종 1마리 월별 적합도 곡선.
    monthly mean (sst, salinity) 를 features 로부터 산출.
    """
    sub = features[features["region"] == region].copy()
    sub["month"] = sub["date"].dt.month
    monthly = sub.groupby("month").agg(sst=("sst", "mean"),
                                        salinity=("salinity", "mean")).reset_index()
    sst_year = [None] * 12
    sal_year = [None] * 12
    for _, r in monthly.iterrows():
        m = int(r["month"]) - 1
        sst_year[m] = float(r["sst"]) if pd.notna(r["sst"]) else None
        sal_year[m] = float(r["salinity"]) if pd.notna(r["salinity"]) else None
    # 결측 월은 인접 월 보간
    for i in range(12):
        if sst_year[i] is None:
            non_null = [v for v in sst_year if v is not None]
            sst_year[i] = sum(non_null) / len(non_null) if non_null else 18.0
        if sal_year[i] is None:
            non_null = [v for v in sal_year if v is not None]
            sal_year[i] = sum(non_null) / len(non_null) if non_null else 33.0
    curve = seasonal_curve(species_id, sst_year, sal_year)
    sp = get_species(species_id)
    return {
        "region": region, "species_id": species_id, "ko": sp["ko"] if sp else None,
        "monthly_probability": [round(p, 4) for p in curve],
        "monthly_sst": [round(v, 2) for v in sst_year],
        "monthly_salinity": [round(v, 2) for v in sal_year],
    }
