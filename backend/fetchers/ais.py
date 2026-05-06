"""AIS 어선 위치 데이터 수집 모듈.

데이터 소스 후보 (PoC 시작 시 1곳 선택):
  1) 해양수산부 어선위치정보 (data.go.kr) — 한국 어선 한정, 정부 공식
     https://www.data.go.kr/  검색: "어선위치"
  2) MarineTraffic API — 글로벌, 유료 (월 수십~수백 USD)
     https://www.marinetraffic.com/en/ais-api-services
  3) AISHub — 무료 피드, 회원사 데이터 공유 의무 (자체 수신기 필요)
     https://www.aishub.net/
  4) AISStream.io — WebSocket 무료 (테스트용)
     https://aisstream.io/

본 모듈은 드론 모듈과 같이 **파일 드롭** 방식을 1차 인터페이스로 한다.
실시간 소스가 결정되면 fetch_realtime_*() 어댑터를 추가한다.

스키마 (AISFix):
    timestamp     ISO8601 UTC
    mmsi          해상이동업무식별번호 (int, 9자리)
    lat, lon      WGS84
    sog_kts       Speed Over Ground (knots)
    cog_deg       Course Over Ground (0~359.9°)
    heading_deg   선수방위 (NaN 허용)
    nav_status    항행상태 코드 (0~15, AIS 표준)
    vessel_type   AIS 30 (어선) / 31 (예인) 등
    name          선명 (str, 옵션)
    length_m      선박 길이 (float, 옵션)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

ARTIFACT_DIR = Path(__file__).parent.parent / "artifacts" / "ais"
INCOMING_DIR = ARTIFACT_DIR / "incoming"
CONSOLIDATED = ARTIFACT_DIR / "fixes.parquet"

FIX_COLS = [
    "timestamp", "mmsi", "lat", "lon", "sog_kts", "cog_deg",
    "heading_deg", "nav_status", "vessel_type", "name", "length_m",
]

# AIS vessel type 코드 — 어업/예인/일반 식별용
VESSEL_TYPE_FISHING = 30
VESSEL_TYPE_TUG = {31, 32, 52}


@dataclass
class AISFix:
    timestamp: datetime
    mmsi: int
    lat: float
    lon: float
    sog_kts: float = 0.0
    cog_deg: float = 0.0
    heading_deg: float | None = None
    nav_status: int | None = None
    vessel_type: int | None = None
    name: str = ""
    length_m: float | None = None


@dataclass
class IngestReport:
    files_seen: int = 0
    rows_added: int = 0
    rows_rejected: int = 0
    errors: list[str] = field(default_factory=list)
    consolidated_total: int = 0


# ============================================================
# 파일 드롭 인제스트
# ============================================================

def _normalize_frame(df: pd.DataFrame, source: str) -> tuple[pd.DataFrame, list[str]]:
    errs: list[str] = []
    df = df.copy()

    rename = {
        "ts": "timestamp", "time": "timestamp", "datetime": "timestamp",
        "latitude": "lat", "longitude": "lon", "lng": "lon",
        "sog": "sog_kts", "speed": "sog_kts", "speed_kn": "sog_kts",
        "cog": "cog_deg", "course": "cog_deg",
        "heading": "heading_deg",
        "vt": "vessel_type", "type": "vessel_type", "ship_type": "vessel_type",
        "ship_name": "name", "vessel_name": "name",
        "length": "length_m",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    required = {"timestamp", "mmsi", "lat", "lon"}
    missing = required - set(df.columns)
    if missing:
        errs.append(f"{source}: 필수 컬럼 누락 {missing}")
        return pd.DataFrame(columns=FIX_COLS), errs

    for c in FIX_COLS:
        if c not in df.columns:
            df[c] = pd.NA

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df["mmsi"] = pd.to_numeric(df["mmsi"], errors="coerce").astype("Int64")
    for c in ("lat", "lon", "sog_kts", "cog_deg", "heading_deg", "length_m"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["nav_status"] = pd.to_numeric(df["nav_status"], errors="coerce").astype("Int64")
    df["vessel_type"] = pd.to_numeric(df["vessel_type"], errors="coerce").astype("Int64")
    df["name"] = df["name"].fillna("").astype(str).str.strip()

    invalid = df["timestamp"].isna() | df["mmsi"].isna() | df["lat"].isna() | df["lon"].isna()
    if invalid.any():
        errs.append(f"{source}: {int(invalid.sum())}행 잘못된 키 → 폐기")
    df = df[~invalid].copy()
    return df[FIX_COLS], errs


def _read_one(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"지원하지 않는 형식: {path.suffix}")


def ingest_incoming(move_processed: bool = True) -> IngestReport:
    """`artifacts/ais/incoming/` 안의 모든 파일 인제스트."""
    INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    report = IngestReport()

    files = sorted(p for p in INCOMING_DIR.iterdir()
                   if p.is_file() and p.suffix.lower() in (".parquet", ".csv"))
    if not files:
        report.consolidated_total = _count_existing()
        return report
    report.files_seen = len(files)

    frames: list[pd.DataFrame] = []
    for p in files:
        try:
            raw = _read_one(p)
        except Exception as e:
            report.errors.append(f"{p}: 읽기 실패 {e}")
            continue
        norm, errs = _normalize_frame(raw, str(p))
        report.errors.extend(errs)
        report.rows_added += len(norm)
        frames.append(norm)

    if not frames:
        report.consolidated_total = _count_existing()
        return report

    new_df = pd.concat(frames, ignore_index=True)
    if CONSOLIDATED.exists():
        merged = pd.concat([pd.read_parquet(CONSOLIDATED), new_df], ignore_index=True)
    else:
        merged = new_df

    before = len(merged)
    merged = merged.drop_duplicates(subset=["mmsi", "timestamp"], keep="last")
    report.rows_rejected += before - len(merged)

    CONSOLIDATED.parent.mkdir(parents=True, exist_ok=True)
    merged.sort_values("timestamp").to_parquet(CONSOLIDATED, index=False)
    report.consolidated_total = len(merged)

    if move_processed:
        done = INCOMING_DIR / "_processed"
        done.mkdir(exist_ok=True)
        for p in files:
            try:
                p.rename(done / p.name)
            except Exception as e:
                report.errors.append(f"{p}: 이동 실패 {e}")

    return report


def _count_existing() -> int:
    if not CONSOLIDATED.exists():
        return 0
    try:
        return len(pd.read_parquet(CONSOLIDATED, columns=["timestamp"]))
    except Exception:
        return 0


# ============================================================
# 조회 + 어업 활동 추정
# ============================================================

def load_fixes(
    hours: int | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    fishing_only: bool = False,
) -> pd.DataFrame:
    if not CONSOLIDATED.exists():
        return pd.DataFrame(columns=FIX_COLS)
    df = pd.read_parquet(CONSOLIDATED)
    if df.empty:
        return df
    if hours is not None:
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=hours)
        df = df[df["timestamp"] >= cutoff]
    if bbox is not None:
        lat_min, lon_min, lat_max, lon_max = bbox
        df = df[df["lat"].between(lat_min, lat_max) & df["lon"].between(lon_min, lon_max)]
    if fishing_only:
        df = df[df["vessel_type"] == VESSEL_TYPE_FISHING]
    return df.sort_values(["mmsi", "timestamp"]).reset_index(drop=True)


def estimate_fishing_activity(df: pd.DataFrame) -> pd.DataFrame:
    """SOG 1~5 knot 구간을 어업 추정 활동으로 라벨링.

    AIS 학계의 통상적 휴리스틱: 어선이 그물·낚시를 사용할 때
    선속이 1~5kn 사이로 떨어진다. 정지(0kn 근처)는 정박, 5kn 초과는 항행.
    """
    if df.empty:
        out = df.copy()
        out["is_fishing"] = False
        return out
    out = df.copy()
    out["is_fishing"] = (
        (out["sog_kts"].fillna(0) >= 1.0) &
        (out["sog_kts"].fillna(0) <= 5.0) &
        ((out["vessel_type"].fillna(VESSEL_TYPE_FISHING) == VESSEL_TYPE_FISHING))
    )
    return out


def fishing_dwell_summary(hours: int = 24,
                          bbox: tuple[float, float, float, float] | None = None
                          ) -> pd.DataFrame:
    """선박별 최근 N시간 어업 추정 시간 요약 (대시보드용)."""
    df = estimate_fishing_activity(load_fixes(hours=hours, bbox=bbox, fishing_only=True))
    if df.empty:
        return pd.DataFrame(columns=["mmsi", "name", "n_fixes", "fishing_minutes_est"])
    g = df.groupby("mmsi")
    # 단순 추정: 한 fix 가 평균 5분 간격이라 가정 (실제 AIS 송신 주기)
    avg_interval_min = 5
    out = pd.DataFrame({
        "name": g["name"].agg(lambda s: s[s != ""].iloc[0] if (s != "").any() else ""),
        "n_fixes": g.size(),
        "fishing_minutes_est": (g["is_fishing"].sum() * avg_interval_min).astype(int),
    }).reset_index()
    return out.sort_values("fishing_minutes_est", ascending=False)


# ============================================================
# 실시간 어댑터 (PoC 후 채움)
# ============================================================

def fetch_realtime_stream(provider: str, **kwargs) -> Iterable[AISFix]:
    """provider: 'data_go_kr' | 'marinetraffic' | 'aishub' | 'aisstream'."""
    raise NotImplementedError(
        f"provider='{provider}' 실시간 어댑터 미구현. "
        "현재는 ingest_incoming() 으로 파일 드롭만 지원한다. "
        "데이터 소스 결정 후 본 함수를 구현하라."
    )
