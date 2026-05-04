"""NIFS 적조속보 전수 크롤링 → artifacts/redtide_labels.parquet
전체 ~1,106건 글, 약 11~13분 소요 (0.6초 sleep).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

from fetchers.nifs_redtide import _session, fetch_detail, list_bulletins

ARTIFACT = Path(__file__).parent / "artifacts"
ARTIFACT.mkdir(exist_ok=True)
OUT = ARTIFACT / "redtide_labels.parquet"


def main(max_pages: int = 200, sleep: float = 0.6):
    sess = _session()
    print(f"[crawl] 목록 수집 (최대 {max_pages}쪽)")
    idx = list_bulletins(sess, max_pages=max_pages, page_size=20)
    print(f"[crawl] 총 글 {len(idx)}건")

    rows = []
    t0 = time.time()
    for i, e in enumerate(idx, 1):
        try:
            for r in fetch_detail(e.cod_news, posted=e.posted, session=sess):
                rows.append(r.__dict__)
        except Exception as ex:
            print(f"  ! {e.cod_news}: {ex}")
        time.sleep(sleep)
        if i % 50 == 0 or i == len(idx):
            elapsed = time.time() - t0
            eta = elapsed / i * (len(idx) - i)
            print(f"  · 진행 {i}/{len(idx)}  rows={len(rows)}  "
                  f"경과 {elapsed:.0f}s  ETA {eta:.0f}s", flush=True)

    df = pd.DataFrame(rows)
    if not df.empty:
        df["posted"] = pd.to_datetime(df["posted"], errors="coerce")
    df.to_parquet(OUT, index=False)
    print(f"[crawl] 저장: {OUT}  rows={len(df)}  with_density={int(df['density_min'].notna().sum())}")


if __name__ == "__main__":
    pages = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    main(max_pages=pages)
