"""
기상청 ASOS 시간자료 (data.go.kr 1360000/AsosHourlyInfoService).
적조 모델 입력 중 일사량(icsr), 풍속(ws), 기온(ta)을 추출한다.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from .base import GoKrClient

ENDPOINT = "http://apis.data.go.kr/1360000/AsosHourlyInfoService/getWthrDataList"
ENDPOINT_DAILY = "http://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList"

# 적조 관측소와 가장 가까운 ASOS 지점번호 매핑.
# 지점번호: https://data.kma.go.kr 지점정보 참고. 필요 시 보강.
STATION_TO_ASOS = {
    "TY01": 162,  # 통영
    "GJ01": 294,  # 거제
    "NH01": 295,  # 남해
    "YS01": 168,  # 여수
    "WD01": 170,  # 완도
    "JD01": 175,  # 진도(첨찰산) — 대안 261 진도
    "GH01": 262,  # 고흥
    "SC01": 192,  # 진주(사천 인접)
    "BS01": 159,  # 부산
    "US01": 152,  # 울산
    "PH01": 138,  # 포항
    "YD01": 277,  # 영덕
    "MP01": 165,  # 목포
    "GS01": 140,  # 군산
    "IC01": 112,  # 인천
    "JJ01": 184,  # 제주
    "JJ02": 189,  # 서귀포
}


def fetch_asos_hourly(service_key: str, asos_stn_id: int,
                      start: datetime, end: datetime) -> pd.DataFrame:
    """단일 ASOS 지점의 시간자료를 [start, end] 구간으로 조회."""
    client = GoKrClient(service_key=service_key)
    params = {
        "pageNo": 1,
        "numOfRows": 999,            # 최대 한 번에 받을 행
        "dataCd": "ASOS",
        "dateCd": "HR",
        "startDt": start.strftime("%Y%m%d"),
        "startHh": start.strftime("%H"),
        "endDt": end.strftime("%Y%m%d"),
        "endHh": end.strftime("%H"),
        "stnIds": str(asos_stn_id),
    }
    payload = client.get(ENDPOINT, params=params, response_type="JSON")

    # 응답 스키마: response.body.items.item -> list[dict]
    try:
        items = payload["response"]["body"]["items"]["item"]
    except (KeyError, TypeError) as e:
        raise RuntimeError(f"예상치 못한 응답 형식: {payload}") from e

    if isinstance(items, dict):
        items = [items]
    df = pd.DataFrame(items)
    if df.empty:
        return df

    df["timestamp"] = pd.to_datetime(df["tm"])
    rename = {
        "ta": "air_temp",     # 기온 (°C)
        "ws": "wind",         # 풍속 (m/s)
        "icsr": "solar",      # 일사 (MJ/m²)
        "hm": "humidity",     # 습도 (%)
        "rn": "rain",         # 강수 (mm)
    }
    keep = ["timestamp"] + [k for k in rename if k in df.columns]
    df = df[keep].rename(columns=rename)
    for col in df.columns:
        if col == "timestamp":
            continue
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.sort_values("timestamp").reset_index(drop=True)


def fetch_recent(service_key: str, asos_stn_id: int, hours: int = 72) -> pd.DataFrame:
    end = datetime.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    start = end - timedelta(hours=hours)
    return fetch_asos_hourly(service_key, asos_stn_id, start, end)


# 광역해역 → 대표 ASOS 지점번호 (경남 3 region)
REGION_TO_ASOS = {
    "경남서부": 192,   # 진주
    "경남중부": 162,   # 통영
    "경남동부": 159,   # 부산
}


def fetch_asos_daily(service_key: str, asos_stn_id: int,
                     start: datetime, end: datetime) -> pd.DataFrame:
    """ASOS 일자료 (일평균/일적산). 한 번에 최대 999일."""
    from .base import GoKrClient
    client = GoKrClient(service_key=service_key)
    params = {
        "pageNo": 1, "numOfRows": 999,
        "dataCd": "ASOS", "dateCd": "DAY",
        "startDt": start.strftime("%Y%m%d"),
        "endDt": end.strftime("%Y%m%d"),
        "stnIds": str(asos_stn_id),
    }
    payload = client.get(ENDPOINT_DAILY, params=params, response_type="JSON")
    try:
        items = payload["response"]["body"]["items"]["item"]
    except (KeyError, TypeError):
        return pd.DataFrame()
    if isinstance(items, dict):
        items = [items]
    df = pd.DataFrame(items)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["tm"])
    rename = {
        "avgTa": "air_temp",        # 일평균 기온 (°C)
        "avgWs": "wind",            # 일평균 풍속 (m/s)
        "sumGsr": "solar",          # 일적산 일사량 (MJ/m²)
        "sumRn": "rain",            # 일강수량 (mm)
        "avgRhm": "humidity",       # 일평균 습도 (%)
    }
    keep = ["date"] + [k for k in rename if k in df.columns]
    df = df[keep].rename(columns=rename)
    for col in df.columns:
        if col == "date":
            continue
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)
