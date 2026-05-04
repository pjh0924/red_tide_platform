"""KOEM Nemo 동해/서해/제주 추가 다운로드 → 기존 parquet에 병합."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

import config
from fetchers.koem import fetch_nemo_all

ARTIFACT = Path(__file__).parent / "artifacts"
PATH = ARTIFACT / "koem_nemo.parquet"


def main():
    existing = pd.read_parquet(PATH) if PATH.exists() else pd.DataFrame()
    have_oceans = set(existing["oceanNm"].unique()) if not existing.empty else set()
    print(f"기존 데이터 oceanNm: {have_oceans}, rows={len(existing)}")

    new_frames = [existing] if not existing.empty else []
    for ocean in ["동해", "서해", "제주"]:
        if ocean in have_oceans:
            print(f"  - {ocean}: skip (이미 있음)")
            continue
        print(f"\n[{ocean}] 다운로드")
        df = fetch_nemo_all(config.DATA_GO_KR_KEY, ocean_name=ocean, page_size=1000)
        if df.empty:
            print(f"  · 빈 응답")
            continue
        # raw timestamp 재계산 (이전 KOEM 버그 fix 와 동일)
        ym = df["obsrYear"].astype(str) + "-" + df["obsrMt"].astype(str).str.zfill(2) + "-01"
        ym_dt = pd.to_datetime(ym, errors="coerce")
        de_dt = pd.to_datetime(df.get("obsrDe"), errors="coerce")
        df["timestamp"] = de_dt.fillna(ym_dt) if "obsrDe" in df.columns else ym_dt
        new_frames.append(df)
        print(f"  · {ocean}: +{len(df)} rows")

    merged = pd.concat(new_frames, ignore_index=True)
    merged.to_parquet(PATH, index=False)
    print(f"\n저장: {PATH}  total rows={len(merged)}")
    print(f"oceanNm 분포: {merged['oceanNm'].value_counts().to_dict()}")


if __name__ == "__main__":
    main()
