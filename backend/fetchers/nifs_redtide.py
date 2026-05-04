"""
국립수산과학원(NIFS) 적조속보 크롤러.
- 목록 페이지: https://www.nifs.go.kr/board/actionRedtideInfoList.do
- 상세 페이지: http://www.nifs.go.kr/rtm/TRS/450/view.do?codNews={codNews}

상세 페이지 추출:
  발생해역 / 적조생물 / 밀도(개체수/mL) / 수온(℃) / 염분
"""
from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass
from datetime import date
from typing import Iterable

import pandas as pd
import requests
from bs4 import BeautifulSoup

LIST_URL = "https://www.nifs.go.kr/board/actionRedtideInfoList.do"
DETAIL_URL = "http://www.nifs.go.kr/rtm/TRS/450/view.do"
HEADERS = {"User-Agent": "RedTideForecast/0.1 (research; pjhtube@gmail.com)"}


@dataclass
class BulletinIndexEntry:
    no: int
    cod_news: str
    title: str
    department: str
    posted: str  # YYYY-MM-DD


@dataclass
class BulletinRow:
    cod_news: str
    posted: str
    region: str           # 예: "전남 득량만"
    species: str          # 예: "Cochlodinium polykrikoides"
    density_min: float | None  # cells/mL
    density_max: float | None
    sst_min: float | None
    sst_max: float | None
    sal_min: float | None
    sal_max: float | None


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def list_bulletins(session: requests.Session | None = None,
                   max_pages: int = 1, page_size: int = 20) -> list[BulletinIndexEntry]:
    """목록 페이지에서 codNews 항목 수집. 최신순 max_pages 만큼."""
    s = session or _session()
    out: list[BulletinIndexEntry] = []
    for page in range(1, max_pages + 1):
        params = {"selectPage": page}
        r = s.get(LIST_URL, params=params, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        rows = soup.select("table tbody tr")
        if not rows:
            break
        for tr in rows:
            tds = tr.find_all("td")
            if len(tds) < 4:
                continue
            a = tds[1].find("a")
            if not a:
                continue
            m = re.search(r"fnRedtideInfoView\(['\"]([^'\"]+)['\"]\)",
                          a.get("href", "") or a.get("onclick", "") or "")
            if not m:
                continue
            try:
                no_text = re.sub(r"[^\d]", "", tds[0].get_text(strip=True))
                no = int(no_text) if no_text else 0
            except ValueError:
                no = 0
            out.append(BulletinIndexEntry(
                no=no,
                cod_news=m.group(1),
                title=a.get_text(strip=True),
                department=tds[2].get_text(strip=True),
                posted=tds[3].get_text(strip=True),
            ))
        time.sleep(0.5)
    return out


_RANGE_RE = re.compile(r"([-\d.]+)\s*[~∼-]\s*([-\d.]+)")
_SINGLE_RE = re.compile(r"([-\d.]+)")


def _parse_range(text: str) -> tuple[float | None, float | None]:
    text = (text or "").replace(",", "").strip()
    if not text or text in {"-", "~", "ND"}:
        return None, None
    m = _RANGE_RE.search(text)
    if m:
        try:
            return float(m.group(1)), float(m.group(2))
        except ValueError:
            return None, None
    m = _SINGLE_RE.search(text)
    if m:
        try:
            v = float(m.group(1))
            return v, v
        except ValueError:
            return None, None
    return None, None


def fetch_detail(cod_news: str, posted: str | None = None,
                 session: requests.Session | None = None) -> list[BulletinRow]:
    """상세 페이지의 적조 발생 현황 표를 행 단위로 추출."""
    s = session or _session()
    r = s.get(DETAIL_URL, params={"codNews": cod_news}, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")

    table = soup.find("table", class_=re.compile("tbl-type-list"))
    if not table:
        # 캡션으로도 한 번 더 시도
        for t in soup.find_all("table"):
            cap = t.find("caption")
            if cap and "적조" in cap.get_text():
                table = t
                break
    if not table:
        return []

    rows: list[BulletinRow] = []
    for tr in table.select("tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue
        region = tds[0].get_text(" ", strip=True)
        species = tds[1].get_text(" ", strip=True)
        d_min, d_max = _parse_range(tds[2].get_text(" ", strip=True))
        s_min, s_max = _parse_range(tds[3].get_text(" ", strip=True))
        sa_min, sa_max = _parse_range(tds[4].get_text(" ", strip=True))
        rows.append(BulletinRow(
            cod_news=cod_news,
            posted=posted or "",
            region=region,
            species=species,
            density_min=d_min, density_max=d_max,
            sst_min=s_min, sst_max=s_max,
            sal_min=sa_min, sal_max=sa_max,
        ))
    return rows


def crawl(max_list_pages: int = 5, sleep_sec: float = 0.6) -> pd.DataFrame:
    """목록 max_list_pages → 각 글 상세 → 평면 DataFrame."""
    s = _session()
    index = list_bulletins(s, max_pages=max_list_pages)
    all_rows: list[BulletinRow] = []
    for i, entry in enumerate(index, 1):
        try:
            rows = fetch_detail(entry.cod_news, posted=entry.posted, session=s)
            all_rows.extend(rows)
        except Exception as e:
            print(f"  ! detail 실패 {entry.cod_news}: {e}")
        time.sleep(sleep_sec)
    df = pd.DataFrame([asdict(r) for r in all_rows])
    if not df.empty:
        df["posted"] = pd.to_datetime(df["posted"], errors="coerce")
    return df
