"""Copernicus Marine Sentinel/multi-sensor 위성 클로로필-a 일별 다운로드.
데이터셋: cmems_obs-oc_glo_bgc-plankton_my_l4-gapfree-multi-4km_P1D
변수: CHL (mg/m³ ≡ µg/L)
저장: artifacts/satellite_chl_daily.parquet  (region × date × chl_sat)
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import copernicusmarine as cm
import numpy as np
import pandas as pd

import config

ARTIFACT = Path(__file__).parent / "artifacts"
OUT = ARTIFACT / "satellite_chl_daily.parquet"

DATASET_ID = "cmems_obs-oc_glo_bgc-plankton_my_l4-gapfree-multi-4km_P1D"

# 광역해역별 bounding box (lat_min, lat_max, lon_min, lon_max)
REGION_BBOX = {
    "남해": (33.0, 35.6, 126.0, 130.0),
    "동해": (35.0, 38.5, 129.0, 131.5),
    "서해": (34.0, 38.0, 124.0, 126.6),
    "제주": (32.7, 34.2, 125.8, 127.6),
}


def fetch_region(region: str, start: str, end: str) -> pd.DataFrame:
    la_min, la_max, lo_min, lo_max = REGION_BBOX[region]
    print(f"  · {region}  bbox=({la_min},{la_max},{lo_min},{lo_max})  {start}~{end}", flush=True)
    ds = cm.open_dataset(
        dataset_id=DATASET_ID,
        username=config.COPERNICUS_USERNAME,
        password=config.COPERNICUS_PASSWORD,
        minimum_longitude=lo_min, maximum_longitude=lo_max,
        minimum_latitude=la_min, maximum_latitude=la_max,
        start_datetime=start, end_datetime=end,
        variables=["CHL"],
    )
    # 영역 평균 → 일별 시계열
    chl_mean = ds["CHL"].mean(dim=["latitude", "longitude"]).compute()
    df = pd.DataFrame({
        "date": pd.to_datetime(chl_mean["time"].values).normalize(),
        "chl_sat": chl_mean.values.astype(float),
    })
    df["region"] = region
    return df


def main(start_year: int = 2016, end_year: int = 2025):
    """Sentinel-3 OLCI 가 2016 부터 운영. l4 multi 는 더 길지만 2016 이후 일관."""
    frames = []
    for region in REGION_BBOX:
        try:
            df = fetch_region(
                region,
                start=f"{start_year}-01-01T00:00:00",
                end=f"{end_year}-12-31T00:00:00",
            )
            frames.append(df)
            print(f"    rows={len(df)}  notna={int(df['chl_sat'].notna().sum())}", flush=True)
        except Exception as e:
            print(f"    FAIL {region}: {e}", flush=True)
    if not frames:
        raise SystemExit("받은 데이터 없음")
    full = pd.concat(frames, ignore_index=True)[["region", "date", "chl_sat"]]
    full.to_parquet(OUT, index=False)
    print(f"\n저장: {OUT}  rows={len(full)}")
    print(full.groupby("region").agg(
        n=("date", "count"),
        date_min=("date", "min"),
        date_max=("date", "max"),
        chl_mean=("chl_sat", "mean"),
        chl_notna=("chl_sat", lambda x: x.notna().sum()),
    ))


if __name__ == "__main__":
    main()
