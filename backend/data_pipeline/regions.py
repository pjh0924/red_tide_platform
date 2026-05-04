"""
적조 광역 해역 정의 (경남 3개로 한정).

본 사업 범위: 남해안 중 경남 (서부 / 중부 / 동부) 만 예측 대상.
- 전남, 제주, 동해, 서해는 fetcher 단계에서는 보유하나 모델/UI 에서는 제외.
"""
from __future__ import annotations

import re

REGIONS = ["경남서부", "경남중부", "경남동부"]


# NIFS 적조속보 자유텍스트 → 경남 3 region 매핑
_NIFS_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"경남.*(부산|울산|동부 ?앞바다|기장|감천)"), "경남동부"),
    (re.compile(r"부산|울산|기장|감천"), "경남동부"),
    (re.compile(r"경남.*(통영|거제 ?서|고성|진해|마산|중부 ?앞바다|자란만)"), "경남중부"),
    (re.compile(r"경남.*(거제)"), "경남중부"),
    (re.compile(r"통영|거제|고성|진해|마산|자란만"), "경남중부"),
    (re.compile(r"경남.*(남해|사천|하동|미조)"), "경남서부"),
    (re.compile(r"^남해|사천|하동"), "경남서부"),
]


def map_to_region(free_text: str | None) -> str | None:
    """NIFS 발생해역 자유텍스트 → 3개 경남 region. 비-경남은 None."""
    if not free_text:
        return None
    text = re.sub(r"\s+", " ", free_text).strip()
    for pattern, region in _NIFS_RULES:
        if pattern.search(text):
            return region
    return None


# KOEM 정점명(stnpntKoreanNm) → 경남 region 매핑
_KOEM_STATION_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"부산|울산|기장|감천"), "경남동부"),
    (re.compile(r"통영|고성|진해|마산|자란만|거제도남안|거제도서안"), "경남중부"),
    (re.compile(r"거제"), "경남중부"),
    (re.compile(r"^남해|사천|하동"), "경남서부"),
]


def map_koem_station_to_region(name: str | None,
                                eclgy: str | None = None) -> str | None:
    """KOEM 정점명 (+eclgyZoneAreaNm) → 경남 region. 매칭 실패시 None."""
    if not name:
        return None
    if eclgy and eclgy != "대한해협":
        # 대한해협 (=경남/부울) 외 (서남해역=전남, 제주) 는 제외
        return None
    for pattern, region in _KOEM_STATION_RULES:
        if pattern.search(name):
            return region
    return None


# 적조 모델 가상 관측소 → 경남 3 region (frontend 매핑)
STATION_TO_REGION = {
    "NH01": "경남서부",   # 남해
    "SC01": "경남서부",   # 사천
    "TY01": "경남중부",   # 통영
    "GJ01": "경남중부",   # 거제
    "GS01": "경남중부",   # 고성
    "JH01": "경남중부",   # 진해 (행정상 창원시 진해구)
    "BS01": "경남동부",   # 부산
    "US01": "경남동부",   # 울산
}
