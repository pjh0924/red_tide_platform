"""실시간 데이터 fetcher + in-memory cache.

현재 가능한 source:
  - KMA ASOS 시간자료 (일사/풍속/기온/습도/강수)
  - KHOA 부이 (활성화되면 자동 추가, 현재 HTTP 500)

캐시: TTL 5분 (ASOS 갱신 주기와 비슷). region 별로 dict 보관.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from threading import Lock
from typing import Any

import pandas as pd
import requests

import config
from fetchers.kma_asos import REGION_TO_ASOS, fetch_asos_hourly

CACHE_TTL_SEC = 300  # 5분
_cache: dict[tuple[str, int], tuple[float, pd.DataFrame]] = {}
_lock = Lock()


def get_realtime_asos(region: str, hours: int = 48) -> pd.DataFrame:
    """region 의 최근 N시간 ASOS 시간자료. 5분 캐시."""
    key = ("asos", region, hours)
    now = time.time()
    with _lock:
        if key in _cache:
            ts, df = _cache[key]
            if now - ts < CACHE_TTL_SEC:
                return df.copy()

    stn = REGION_TO_ASOS.get(region)
    if stn is None:
        return pd.DataFrame()
    # KMA ASOS hourly API 는 "전날까지만 제공" (오늘 자료 요청 시 resultCode=99)
    # → end 를 어제 23:00 으로 강제. 진짜 실시간은 KHOA 부이 활성화 대기.
    today_midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    end = today_midnight - timedelta(hours=1)
    start = end - timedelta(hours=hours)
    try:
        df = fetch_asos_hourly(config.KMA_API_KEY, stn, start, end)
    except Exception as e:
        # 실패 시 빈 DF 반환 (이전 캐시 있으면 그것 사용)
        with _lock:
            if key in _cache:
                return _cache[key][1].copy()
        print(f"[realtime] ASOS fetch 실패 {region}: {e}")
        return pd.DataFrame()

    with _lock:
        _cache[key] = (now, df)
    return df.copy()


# KHOA 부이/조위 fetcher — endpoint 활성화되면 여기에 추가.
KHOA_BUOY_ENDPOINT = "https://apis.data.go.kr/1192136/twRecent"
KHOA_TIDE_TEMP_ENDPOINT = "https://apis.data.go.kr/1192136/surveyWaterTemp"


def get_realtime_khoa_buoy(obs_code: str, hours: int = 24) -> pd.DataFrame:
    """KHOA 해양관측부이 실측 수온. 현재 endpoint HTTP 500 으로 빈 DF 반환."""
    try:
        r = requests.get(
            KHOA_BUOY_ENDPOINT,
            params={"serviceKey": config.DATA_GO_KR_KEY, "type": "json",
                    "obsCode": obs_code, "numOfRows": 100},
            timeout=10,
        )
        if r.status_code != 200:
            return pd.DataFrame()
        # TODO: 실제 응답 형식 파악 후 정규화
        data = r.json()
        items = (data.get("response", {}).get("body", {}).get("items") or
                 data.get("result", {}).get("data") or [])
        if isinstance(items, dict):
            items = items.get("item", [])
        return pd.DataFrame(items)
    except Exception:
        return pd.DataFrame()


def is_khoa_available() -> bool:
    """KHOA endpoint 가 정상 응답하는지 가벼운 헬스체크 (한 번만 캐시)."""
    if not hasattr(is_khoa_available, "_checked"):
        try:
            r = requests.get(
                KHOA_BUOY_ENDPOINT,
                params={"serviceKey": config.DATA_GO_KR_KEY, "type": "json",
                        "obsCode": "DT_0001"},
                timeout=5,
            )
            is_khoa_available._checked = (r.status_code == 200)
        except Exception:
            is_khoa_available._checked = False
    return is_khoa_available._checked


def realtime_summary(region: str, hours: int = 48) -> dict[str, Any]:
    """실시간 환경 변수 요약 + 시계열."""
    asos = get_realtime_asos(region, hours)
    if asos.empty:
        return {"region": region, "asos": [], "khoa_available": is_khoa_available()}

    asos = asos.sort_values("timestamp")
    series = []
    for _, r in asos.iterrows():
        row = {"timestamp": r["timestamp"].isoformat()}
        for c in ["air_temp", "wind", "solar", "humidity", "rain"]:
            v = r.get(c)
            if pd.notna(v):
                row[c] = float(v)
            else:
                row[c] = None
        series.append(row)

    last = asos.iloc[-1]
    summary = {
        "region": region,
        "issued_at": datetime.now().isoformat(),
        "latest": {
            "timestamp": last["timestamp"].isoformat(),
            "air_temp": float(last["air_temp"]) if pd.notna(last.get("air_temp")) else None,
            "wind": float(last["wind"]) if pd.notna(last.get("wind")) else None,
            "solar": float(last["solar"]) if pd.notna(last.get("solar")) else None,
        },
        "asos": series,
        "khoa_available": is_khoa_available(),
    }
    return summary
