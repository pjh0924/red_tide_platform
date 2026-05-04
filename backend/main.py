"""FastAPI 적조예측 API 서버 (v2: 실데이터 기반 광역해역 위험도)."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from data_pipeline.features import build_features, load_koem_measurements
from data_pipeline.labels import build_daily_labels
from data_pipeline.realtime import realtime_summary
from data_pipeline.regions import REGIONS, STATION_TO_REGION
from model_v2 import HORIZONS, RedTideRiskModel, risk_color, risk_level
from stations import STATIONS, get_station

ARTIFACT = Path(__file__).parent / "artifacts"
FRONTEND = Path(__file__).parent.parent / "frontend"
MODEL_PATH = ARTIFACT / "risk_model_v2.joblib"

app = FastAPI(title="적조예측 플랫폼 v2", version="0.2.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

_model: RedTideRiskModel | None = None
_features: pd.DataFrame | None = None
_labels: pd.DataFrame | None = None
_measurements: pd.DataFrame | None = None   # KOEM raw 측정점 (forward-fill 안 함)


def _load():
    global _model, _features, _labels, _measurements
    if _model is None:
        if not MODEL_PATH.exists():
            raise HTTPException(503, "모델 미학습. `python train_v2.py` 실행 필요.")
        _model = RedTideRiskModel.load(MODEL_PATH)
    if _features is None:
        _features = build_features(2010, datetime.now().year)
    if _labels is None:
        try:
            _labels = build_daily_labels(2010, datetime.now().year)
        except FileNotFoundError:
            _labels = None
    if _measurements is None:
        try:
            _measurements = load_koem_measurements()
        except FileNotFoundError:
            _measurements = None


def _region_today_features(region: str) -> pd.DataFrame:
    """해당 region의 오늘 시점 입력 features 1행."""
    _load()
    today = pd.Timestamp(datetime.now().date())
    sub = _features[(_features["region"] == region) & (_features["date"] <= today)]
    if sub.empty:
        raise HTTPException(404, f"region {region} 데이터 없음")
    return sub.tail(1)


def _region_forecast(region: str) -> dict:
    """region 의 향후 1/3/7일 발생 확률 예측."""
    _load()
    feats = _region_today_features(region)
    proba = _model.predict_proba(feats[_model.feature_cols])
    issued = pd.Timestamp(datetime.now().replace(microsecond=0))
    out = []
    for h in HORIZONS:
        p = float(proba[h][0])
        out.append({
            "horizon_days": h,
            "probability": round(p, 4),
            "level": risk_level(p),
            "color": risk_color(p),
            "valid_until": (issued + timedelta(days=h)).isoformat(),
        })
    return {"region": region, "issued_at": issued.isoformat(), "horizons": out}


@app.get("/api/regions")
def regions():
    """4개 광역 해역 + 현재 위험도."""
    out = []
    for r in REGIONS:
        try:
            f = _region_forecast(r)
            cur = next((h for h in f["horizons"] if h["horizon_days"] == 1), f["horizons"][0])
            out.append({
                "region": r,
                "current_probability": cur["probability"],
                "current_level": cur["level"],
                "color": cur["color"],
                "issued_at": f["issued_at"],
            })
        except HTTPException as e:
            out.append({"region": r, "error": e.detail, "current_level": "안전",
                         "color": risk_color(0.0)})
    return out


@app.get("/api/regions/{region}/forecast")
def region_forecast(region: str):
    """광역 해역의 향후 1/3/7일 발생 확률."""
    if region not in REGIONS:
        raise HTTPException(404, f"region '{region}' 없음 (가능: {REGIONS})")
    return _region_forecast(region)


@app.get("/api/regions/{region}/observations")
def region_observations(region: str, days: int = 730):
    """해당 region 의 KOEM 실제 측정점 시계열 (분기/월 단위, forward-fill 없음)."""
    _load()
    if region not in REGIONS:
        raise HTTPException(404, f"region '{region}' 없음")
    if _measurements is None:
        return []
    cutoff = pd.Timestamp(datetime.now().date()) - timedelta(days=days)
    sub = _measurements[
        (_measurements["region"] == region) & (_measurements["date"] >= cutoff)
    ].copy()
    sub = sub.dropna(subset=["sst"], how="all").sort_values("date")
    sub["date"] = sub["date"].dt.strftime("%Y-%m-%d")
    keep = ["date", "sst", "salinity", "din", "dip", "do", "chl_a"]
    out = sub[[c for c in keep if c in sub.columns]]
    out = out.astype(object).where(out.notna(), None)
    return out.to_dict(orient="records")


@app.get("/api/regions/{region}/realtime")
def region_realtime(region: str, hours: int = 48):
    """KMA ASOS 시간자료 (최근 hours 시간) + KHOA 가용성. 5분 캐시."""
    if region not in REGIONS:
        raise HTTPException(404, f"region '{region}' 없음")
    return realtime_summary(region, hours=hours)


@app.get("/api/regions/{region}/history")
def region_history(region: str, days: int = 365):
    """NIFS 적조 발생 이력 (region 단위)."""
    _load()
    if _labels is None:
        return []
    cutoff = pd.Timestamp(datetime.now().date()) - timedelta(days=days)
    sub = _labels[(_labels["region"] == region) & (_labels["date"] >= cutoff) &
                  (_labels["bloom"] == 1)].copy()
    sub["date"] = sub["date"].dt.strftime("%Y-%m-%d")
    cols = ["date", "density_max", "level", "n_records"]
    out = sub[[c for c in cols if c in sub.columns]]
    # NaN → None 변환 (JSON 호환). object dtype 으로 캐스트 후 where 으로 NaN 제거.
    out = out.astype(object).where(out.notna(), None)
    return out.to_dict(orient="records")


@app.get("/api/stations")
def stations():
    """17개 가상 관측소 + 소속 region 의 현재 위험도."""
    region_status = {r["region"]: r for r in regions()}
    out = []
    for s in STATIONS:
        region = STATION_TO_REGION.get(s["id"])
        rs = region_status.get(region, {})
        out.append({
            **s,
            "region_assigned": region,
            "current_probability": rs.get("current_probability"),
            "current_level": rs.get("current_level", "안전"),
            "color": rs.get("color", risk_color(0.0)),
        })
    return out


@app.get("/api/summary")
def summary():
    rs = regions()
    counts = {"안전": 0, "관심": 0, "주의보": 0, "경보": 0}
    for r in rs:
        counts[r.get("current_level", "안전")] = counts.get(r.get("current_level", "안전"), 0) + 1
    return {
        "regions": counts,
        "total_regions": len(rs),
        "total_stations": len(STATIONS),
        "issued_at": datetime.utcnow().isoformat(),
    }


# 정적 프론트엔드
if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

    @app.get("/")
    def root():
        return FileResponse(FRONTEND / "index.html")
