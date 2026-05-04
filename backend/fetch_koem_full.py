"""KOEM 해양환경측정망 측정값 전수 다운로드 → artifacts/koem_nemo.parquet"""
from __future__ import annotations

from pathlib import Path

import config
from fetchers.koem import fetch_nemo_all, fetch_station_catalog

ARTIFACT = Path(__file__).parent / "artifacts"
ARTIFACT.mkdir(exist_ok=True)


def main():
    if not config.DATA_GO_KR_KEY:
        raise SystemExit("DATA_GO_KR_KEY 미설정")

    print("[1] 정점 카탈로그 (남해+서남해+동남해 기준 근해)")
    cats = []
    for ocean in ["남해", "동해", "서해"]:
        try:
            c = fetch_station_catalog(config.DATA_GO_KR_KEY, kind="nsea", ocean_name=ocean)
            print(f"  · {ocean}: {len(c)} 정점")
            cats.append(c)
        except Exception as e:
            print(f"  ! {ocean}: {e}")
    if cats:
        import pandas as pd
        cat = pd.concat(cats, ignore_index=True)
        cat.to_parquet(ARTIFACT / "koem_stations.parquet", index=False)
        print(f"  → 저장: koem_stations.parquet  rows={len(cat)}")

    print("\n[2] Nemo 측정값 전수 (남해 우선)")
    df = fetch_nemo_all(config.DATA_GO_KR_KEY, ocean_name="남해", page_size=1000)
    out = ARTIFACT / "koem_nemo.parquet"
    df.to_parquet(out, index=False)
    print(f"\n저장: {out}  rows={len(df)}  columns={list(df.columns)}")
    if not df.empty:
        print(f"\n연도별 행 수:\n{df['obsrYear'].value_counts().sort_index().tail(10)}")
        print(f"\n비결측 비율 (주요 변수):")
        for c in ["sst", "salinity", "din", "dip", "do", "chl_a"]:
            if c in df.columns:
                print(f"  {c:10s}: {df[c].notna().mean()*100:.1f}%")


if __name__ == "__main__":
    main()
