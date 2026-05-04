"""
해양환경공단(KOEM) 해양환경측정망 fetcher (data.go.kr B553931).

검증된 엔드포인트 (2026-05 기준):
- OceansNemoService2/getOceansNemo2     : 측정망 측정값 (V2!)
- OceansNseaInfoService1/getOceansNseaInfo1   : 근해 정점 카탈로그
- OceansWemoReInfoService1/getOceansWemoReInfo1 : 자동측정망(하구/만) 정점 카탈로그

특이사항:
- 응답은 항상 XML (resultType=JSON 무시됨).
- Nemo 측정값 API 의 날짜 파라미터(INVST_BGN_DATE 등)는 무시됨.
  → 클라이언트 측에서 obsrYear/obsrMt 로 후처리 필터링.
- 페이지네이션은 정상 작동. totalCount 약 42,000+ (1997~ 누적).
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from typing import Any

import pandas as pd
import requests

BASE = "https://apis.data.go.kr/B553931/service"

ENDPOINTS = {
    "nemo": f"{BASE}/OceansNemoService2/getOceansNemo2",
    "nsea_info": f"{BASE}/OceansNseaInfoService1/getOceansNseaInfo1",
    "wemo_info": f"{BASE}/OceansWemoReInfoService1/getOceansWemoReInfo1",
}

# 적조 모델 컬럼 ← KOEM Nemo 표층 측정값 매핑
NEMO_FIELD_MAP = {
    "wtrtmpSfclyr": "sst",
    "salntSfclyr": "salinity",
    "phDnstySfclyr": "ph",
    "doxySfclyr": "do",
    "choxdmSfclyr": "cod",
    "nh4nSfclyr": "nh4",
    "no2nSfclyr": "no2",
    "no3nSfclyr": "no3",
    "dinSfclyr": "din",
    "totnSfclyr": "tn",
    "dipSfclyr": "dip",
    "totpSfclyr": "tp",
    "slcacdSiSfclyr": "si",
    "fltngMttrSfclyr": "ss",
    "clrplaSfclyr": "chl_a",
}
META_FIELDS = ["oceanCode", "oceanNm", "eclgyZoneAreaCode", "eclgyZoneAreaNm",
               "stnpntCode", "stnpntKoreanNm", "obsrYear", "obsrMt", "obsrDe", "wethr"]


def _xml_items_to_records(xml_text: str) -> list[dict]:
    """XML 응답 → 평면 레코드 리스트."""
    root = ET.fromstring(xml_text)
    rc = root.findtext("./header/resultCode") or "?"
    if rc != "00":
        msg = root.findtext("./header/resultMsg") or ""
        raise RuntimeError(f"KOEM 에러 resultCode={rc} msg={msg}")
    items = root.findall("./body/items/item")
    out = []
    for it in items:
        out.append({child.tag: (child.text.strip() if child.text else None)
                    for child in it})
    return out


def _xml_total_count(xml_text: str) -> int:
    root = ET.fromstring(xml_text)
    txt = root.findtext("./body/totalCount") or "0"
    try:
        return int(txt)
    except ValueError:
        return 0


def _get(url: str, service_key: str, params: dict[str, Any] | None = None,
         timeout: float = 20.0, retries: int = 3) -> str:
    p = dict(params or {})
    p["serviceKey"] = service_key
    p.setdefault("resultType", "xml")
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=p, timeout=timeout)
            r.raise_for_status()
            if "<resultCode>" not in r.text:
                raise RuntimeError(f"비정상 응답: {r.text[:200]}")
            return r.text
        except (requests.RequestException, RuntimeError) as e:
            last_err = e
            time.sleep(1.5 ** attempt)
    raise RuntimeError(f"요청 실패: {last_err}")


def fetch_station_catalog(service_key: str, kind: str = "nsea",
                          ocean_name: str | None = None,
                          page_size: int = 500) -> pd.DataFrame:
    """정점 카탈로그. kind: 'nsea' (근해) | 'wemo' (자동측정망 하구/만)."""
    key = "nsea_info" if kind == "nsea" else "wemo_info"
    params: dict[str, Any] = {"pageNo": 1, "numOfRows": page_size}
    if ocean_name:
        params["OCEAN_NM"] = ocean_name
    xml = _get(ENDPOINTS[key], service_key, params=params)
    df = pd.DataFrame(_xml_items_to_records(xml))
    if df.empty:
        return df
    for c in ("lon", "lat"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def fetch_nemo_all(service_key: str, ocean_name: str | None = None,
                   page_size: int = 1000, max_pages: int | None = None,
                   sleep: float = 0.4, progress: bool = True) -> pd.DataFrame:
    """KOEM Nemo 측정값 페이지 순회 다운로드.
    - ocean_name 으로 1차 필터 (서버측: '동해'/'남해'/'서해'/'제주' 등)
    - 날짜 필터는 서버에서 무시되므로, 받은 후 obsrYear/obsrMt 로 후처리 필터링하라.
    """
    params0: dict[str, Any] = {"pageNo": 1, "numOfRows": 1}
    if ocean_name:
        params0["OCEAN_NM"] = ocean_name
    head_xml = _get(ENDPOINTS["nemo"], service_key, params=params0)
    total = _xml_total_count(head_xml)
    pages = (total + page_size - 1) // page_size
    if max_pages:
        pages = min(pages, max_pages)
    if progress:
        print(f"[koem.nemo] total={total}  page_size={page_size}  pages={pages}")

    all_rows: list[dict] = []
    for p in range(1, pages + 1):
        params: dict[str, Any] = {"pageNo": p, "numOfRows": page_size}
        if ocean_name:
            params["OCEAN_NM"] = ocean_name
        xml = _get(ENDPOINTS["nemo"], service_key, params=params)
        rows = _xml_items_to_records(xml)
        all_rows.extend(rows)
        if progress and (p % 5 == 0 or p == pages):
            print(f"  · page {p}/{pages}  acc rows={len(all_rows)}", flush=True)
        time.sleep(sleep)
    df = pd.DataFrame(all_rows)
    return _normalize_nemo(df)


def _normalize_nemo(df: pd.DataFrame) -> pd.DataFrame:
    """KOEM Nemo 응답 → 모델 친화 컬럼명 + 타임스탬프."""
    if df.empty:
        return df
    out_cols = {}
    for src, dst in NEMO_FIELD_MAP.items():
        if src in df.columns:
            out_cols[dst] = pd.to_numeric(df[src], errors="coerce")
    out = pd.DataFrame(out_cols)
    for c in META_FIELDS:
        if c in df.columns:
            out[c] = df[c]
    if "obsrYear" in out.columns and "obsrMt" in out.columns:
        # obsrDe 는 보통 "2019-05-08" 같은 풀 ISO 문자열 또는 NaN.
        # 1순위: obsrDe 가 valid date 면 그대로
        # 2순위: obsrYear-obsrMt-01 fallback
        ym = (out["obsrYear"].astype(str) + "-" +
              out["obsrMt"].astype(str).str.zfill(2) + "-01")
        ym_dt = pd.to_datetime(ym, errors="coerce")
        if "obsrDe" in out.columns:
            de_dt = pd.to_datetime(out["obsrDe"], errors="coerce")
            out["timestamp"] = de_dt.fillna(ym_dt)
        else:
            out["timestamp"] = ym_dt
    return out
