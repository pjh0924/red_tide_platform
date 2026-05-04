"""KMA ASOS 일자료 과거 다운로드 → artifacts/asos_daily.parquet"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

import config
from fetchers.kma_asos import REGION_TO_ASOS, fetch_asos_daily

ARTIFACT = Path(__file__).parent / "artifacts"
ARTIFACT.mkdir(exist_ok=True)
OUT = ARTIFACT / "asos_daily.parquet"


def main(start_year: int = 2010, end_year: int = 2025):
    if not config.KMA_API_KEY:
        raise SystemExit("KMA_API_KEY 미설정")

    frames = []
    for region, stn in REGION_TO_ASOS.items():
        # 999일 단위 청크 분할 (3년 정도)
        for chunk_start_year in range(start_year, end_year + 1, 3):
            cs = datetime(chunk_start_year, 1, 1)
            ce = datetime(min(chunk_start_year + 2, end_year), 12, 31)
            print(f"  · {region}({stn})  {cs.date()}~{ce.date()}", flush=True)
            df = fetch_asos_daily(config.KMA_API_KEY, stn, cs, ce)
            if not df.empty:
                df["region"] = region
                df["stnId"] = stn
                frames.append(df)
    if not frames:
        raise SystemExit("받은 데이터 없음")
    full = pd.concat(frames, ignore_index=True)
    full.to_parquet(OUT, index=False)
    print(f"\n저장: {OUT}  rows={len(full)}")
    print(full.groupby("region").agg(
        n=("date", "count"),
        date_min=("date", "min"),
        date_max=("date", "max"),
        solar_notna=("solar", lambda x: x.notna().sum()),
    ))


if __name__ == "__main__":
    main()
