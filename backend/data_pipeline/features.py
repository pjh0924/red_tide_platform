"""
광역 해역 × 일별 입력 특성 빌드.

데이터 소스: KOEM Nemo 측정값 (분기/월 단위) → as-of merge → 일별 features.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from .regions import REGIONS, map_koem_station_to_region

ARTIFACT = Path(__file__).resolve().parent.parent / "artifacts"
KOEM_PATH = ARTIFACT / "koem_nemo.parquet"
ASOS_PATH = ARTIFACT / "asos_daily.parquet"
SAT_CHL_PATH = ARTIFACT / "satellite_chl_daily.parquet"
FEATURES_PATH = ARTIFACT / "features_daily.parquet"

NEMO_VARS = ["sst", "salinity", "ph", "do", "din", "dip", "chl_a"]
ASOS_VARS = ["solar", "wind", "air_temp", "rain"]
# 위성 chl-a 는 다운로드만 하고 모델 features 에서는 제외.
# 이유: 2023+ 시점 분포 shift 에 매우 민감해 holdout AUROC 가 0.10 이상 하락.
# 향후 region-aware calibration 또는 추가 feature engineering 후 재통합 가능.
SAT_VARS: list[str] = []
ALL_VARS = NEMO_VARS + ASOS_VARS + SAT_VARS


def load_koem_measurements() -> pd.DataFrame:
    """KOEM 원자료 → (region, date) 단위 측정값. region = oceanNm."""
    if not KOEM_PATH.exists():
        raise FileNotFoundError(f"KOEM 데이터 없음: {KOEM_PATH}")
    df = pd.read_parquet(KOEM_PATH)
    df = df.dropna(subset=["timestamp"]).copy()
    # 경남 3 region 으로 정점명 + 생태구역명 기반 매핑 (oceanNm='남해' 한정)
    df = df[df["oceanNm"] == "남해"].copy()
    df["region"] = df.apply(
        lambda r: map_koem_station_to_region(
            r.get("stnpntKoreanNm"), r.get("eclgyZoneAreaNm")
        ), axis=1,
    )
    df = df.dropna(subset=["region"])
    df["date"] = pd.to_datetime(df["timestamp"]).dt.normalize().astype("datetime64[ns]")
    agg = (
        df.groupby(["region", "date"], as_index=False)[NEMO_VARS].mean()
        .sort_values(["region", "date"])
    )
    return agg


def daily_grid(start_year: int, end_year: int) -> pd.DataFrame:
    days = pd.date_range(date(start_year, 1, 1), date(end_year, 12, 31), freq="D").astype("datetime64[ns]")
    out = pd.MultiIndex.from_product([REGIONS, days], names=["region", "date"]).to_frame(index=False)
    return out


def build_koem_daily(start_year: int = 2010, end_year: int = 2025,
                     max_gap_days: int = 365) -> pd.DataFrame:
    """KOEM 측정값을 일별 그리드에 as-of(backward) merge.
    max_gap_days 안에 직전 측정이 없으면 NaN.
    """
    measurements = load_koem_measurements()
    grid = daily_grid(start_year, end_year)
    parts = []
    for region in REGIONS:
        g = grid[grid["region"] == region].sort_values("date").copy()
        m = measurements[measurements["region"] == region].sort_values("date").copy()
        if m.empty:
            for v in NEMO_VARS:
                g[v] = np.nan
            parts.append(g)
            continue
        merged = pd.merge_asof(
            g, m[["date"] + NEMO_VARS],
            on="date", direction="backward",
            tolerance=pd.Timedelta(days=max_gap_days),
        )
        parts.append(merged)
    out = pd.concat(parts, ignore_index=True)
    return out


def add_seasonal_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    doy = df["date"].dt.dayofyear
    df["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    df["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    df["month"] = df["date"].dt.month
    return df


def add_rolling(df: pd.DataFrame, vars_: list[str], windows: list[int]) -> pd.DataFrame:
    df = df.sort_values(["region", "date"]).copy()
    for w in windows:
        for v in vars_:
            df[f"{v}_r{w}"] = (
                df.groupby("region")[v].transform(lambda s: s.rolling(w, min_periods=1).mean())
            )
    return df


def load_asos_daily() -> pd.DataFrame:
    """KMA ASOS 일자료 로드 (region, date, solar, wind, air_temp, rain)."""
    if not ASOS_PATH.exists():
        return pd.DataFrame(columns=["region", "date"] + ASOS_VARS)
    df = pd.read_parquet(ASOS_PATH)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize().astype("datetime64[ns]")
    keep = ["region", "date"] + [c for c in ASOS_VARS if c in df.columns]
    return df[keep].drop_duplicates(["region", "date"])


def load_satellite_chl() -> pd.DataFrame:
    """Copernicus 위성 chl-a 일별 로드.
    region 별 평균 차이가 큰 raw 값은 train/test shift 에 민감하므로:
      - chl_sat        : 원시 mg/m³
      - chl_sat_anom   : region·month 별 평균 대비 anomaly (log10 스케일)
      - chl_sat_log    : log10 변환
    """
    if not SAT_CHL_PATH.exists():
        return pd.DataFrame(columns=["region", "date"] + SAT_VARS)
    df = pd.read_parquet(SAT_CHL_PATH)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize().astype("datetime64[ns]")
    df["chl_sat_log"] = np.log10(df["chl_sat"].clip(lower=0.01))
    df["month"] = df["date"].dt.month
    region_month_mean = df.groupby(["region", "month"])["chl_sat_log"].transform("mean")
    df["chl_sat_anom"] = df["chl_sat_log"] - region_month_mean
    return df[["region", "date", "chl_sat", "chl_sat_log", "chl_sat_anom"]].drop_duplicates(
        ["region", "date"]
    )


def build_features(start_year: int = 2010, end_year: int = 2025) -> pd.DataFrame:
    daily = build_koem_daily(start_year, end_year)
    asos = load_asos_daily()
    if not asos.empty:
        daily = daily.merge(asos, on=["region", "date"], how="left")
    sat = load_satellite_chl()
    if not sat.empty:
        daily = daily.merge(sat, on=["region", "date"], how="left")
    daily = add_seasonal_features(daily)
    rolling_vars = NEMO_VARS + [v for v in ASOS_VARS + SAT_VARS if v in daily.columns]
    daily = add_rolling(daily, rolling_vars, [7, 30])
    return daily


def save_features(df: pd.DataFrame) -> Path:
    FEATURES_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(FEATURES_PATH, index=False)
    return FEATURES_PATH
