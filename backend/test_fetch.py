"""실제 API 호출 스모크 테스트.
사용: python test_fetch.py
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import config
from fetchers.kma_asos import STATION_TO_ASOS, fetch_asos_hourly
from fetchers.koem import (
    fetch_ctd_observations,
    fetch_nemo_observations,
    fetch_station_catalog,
)


def section(title):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def main():
    if not config.DATA_GO_KR_KEY:
        raise SystemExit("DATA_GO_KR_KEY 미설정")
    key = config.DATA_GO_KR_KEY

    # 1) KMA ASOS (이미 검증됨, 회귀 확인)
    section("[1] KMA ASOS — 부산 어제 0~6시")
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    df = fetch_asos_hourly(key, STATION_TO_ASOS["BS01"], today - timedelta(days=1),
                            today - timedelta(hours=18))
    print(f"rows={len(df)}, cols={list(df.columns)}")
    if not df.empty:
        print(df.head(2).to_string(index=False))

    # 2) KOEM 정점 카탈로그 — 남해
    section("[2] KOEM 근해 정점 카탈로그 — 남해")
    try:
        cat = fetch_station_catalog(key, kind="nsea", ocean_name="남해")
        print(f"rows={len(cat)}, cols={list(cat.columns)}")
        if not cat.empty:
            print(cat.head(3).to_string(index=False))
    except Exception as e:
        print(f"FAIL: {e}")

    # 3) KOEM 자동측정망 정점 카탈로그
    section("[3] KOEM 자동측정망(하구/만) 정점 카탈로그")
    try:
        cat = fetch_station_catalog(key, kind="wemo")
        print(f"rows={len(cat)}, cols={list(cat.columns)}")
        if not cat.empty:
            print(cat.head(3).to_string(index=False))
    except Exception as e:
        print(f"FAIL: {e}")

    # 4) KOEM 측정망 측정값 — 최근 1년 남해
    section("[4] KOEM 해양환경측정망 측정값 — 남해, 2025-01-01 ~ 2025-12-31")
    try:
        obs = fetch_nemo_observations(
            key, ocean_name="남해",
            start=date(2025, 1, 1), end=date(2025, 12, 31),
            page_size=20,
        )
        print(f"rows={len(obs)}, cols={list(obs.columns)}")
        if not obs.empty:
            print(obs.head(3).to_string(index=False))
    except Exception as e:
        print(f"FAIL: {e}")

    # 5) KOEM CTD — 남해
    section("[5] KOEM CTD — 남해 2025년")
    try:
        ctd = fetch_ctd_observations(
            key, ocean_name="남해",
            start=date(2025, 1, 1), end=date(2025, 12, 31),
            page_size=20,
        )
        print(f"rows={len(ctd)}, cols={list(ctd.columns)}")
        if not ctd.empty:
            print(ctd.head(3).to_string(index=False))
    except Exception as e:
        print(f"FAIL: {e}")


if __name__ == "__main__":
    main()
