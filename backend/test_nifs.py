"""NIFS 적조속보 크롤러 스모크 테스트."""
from __future__ import annotations

from fetchers.nifs_redtide import crawl, fetch_detail, list_bulletins


def main():
    print("[1] 목록 페이지 1쪽 (최신 20건)")
    idx = list_bulletins(max_pages=1, page_size=20)
    print(f"  rows={len(idx)}")
    for e in idx[:5]:
        print(f"  - #{e.no} {e.cod_news} {e.posted} | {e.title}")

    if not idx:
        return

    print("\n[2] 첫 글 상세 추출")
    rows = fetch_detail(idx[0].cod_news, posted=idx[0].posted)
    print(f"  rows={len(rows)}")
    for r in rows:
        print(f"  · {r.region} | {r.species} | {r.density_min}~{r.density_max} cells/mL "
              f"| SST {r.sst_min}~{r.sst_max} | sal {r.sal_min}~{r.sal_max}")

    print("\n[3] 통합 크롤 (목록 2쪽 = 40건)")
    df = crawl(max_list_pages=2)
    print(f"  rows={len(df)}, cols={list(df.columns)}")
    if not df.empty:
        print("  샘플:")
        print(df.head(5).to_string(index=False))
        print("  비-결측 밀도 행 수:", df["density_min"].notna().sum())


if __name__ == "__main__":
    main()
