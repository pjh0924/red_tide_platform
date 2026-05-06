"""수상드론 어군 탐지 결과 수집 모듈.

설계 원칙:
- 실제 드론 업체와의 실시간 API 통합은 PoC 진입 후에 추가한다.
- 그 전까지는 **파일 드롭(parquet/csv)** 방식으로 누구나 데이터를 부어 넣을 수 있게 한다.
- 스키마(`DroneDetection`)가 계약이며, 업체가 어떤 포맷이든 이 스키마로 변환만 하면 된다.

데이터 흐름:
    artifacts/drone/incoming/<mission_id>.{parquet|csv}
        → ingest_incoming() 호출 시 1회 통합
        → artifacts/drone/detections.parquet (누적, dedupe 적용)

스키마 (DroneDetection):
    timestamp        ISO8601 UTC (datetime64[ns, UTC] 권장)
    mission_id       드론 출항 식별자 (str)
    lat, lon         WGS84 (float)
    depth_m          탐지 수심 (float, NaN 허용)
    species          어종 코드: 'mackerel'|'sardine'|'anchovy'|'horse_mackerel'
                     |'spanish_mackerel'|'flatfish'|'rockfish'|'unknown'
    confidence       0~1 신뢰도 (float)
    biomass_kg_est   추정 바이오매스 kg (float, NaN 허용)
    sensor           센서 종류: 'soundar'|'sidescan'|'camera'|'lidar'
    raw_path         원본 데이터 경로 (str, 추적용)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

ARTIFACT_DIR = Path(__file__).parent.parent / "artifacts" / "drone"
INCOMING_DIR = ARTIFACT_DIR / "incoming"
CONSOLIDATED = ARTIFACT_DIR / "detections.parquet"

DETECTION_COLS = [
    "timestamp", "mission_id", "lat", "lon", "depth_m",
    "species", "confidence", "biomass_kg_est", "sensor", "raw_path",
]

VALID_SPECIES = {
    "mackerel", "sardine", "anchovy", "horse_mackerel",
    "spanish_mackerel", "flatfish", "rockfish", "unknown",
}
VALID_SENSORS = {"soundar", "sidescan", "camera", "lidar"}


@dataclass
class DroneDetection:
    """단일 드론 탐지 이벤트. fetcher 외부에서 import 해 사용 가능."""
    timestamp: datetime
    mission_id: str
    lat: float
    lon: float
    species: str
    confidence: float
    sensor: str = "soundar"
    depth_m: float | None = None
    biomass_kg_est: float | None = None
    raw_path: str = ""

    def as_row(self) -> dict:
        return {
            "timestamp": pd.Timestamp(self.timestamp).tz_convert("UTC")
                if pd.Timestamp(self.timestamp).tzinfo
                else pd.Timestamp(self.timestamp).tz_localize("UTC"),
            "mission_id": self.mission_id,
            "lat": float(self.lat),
            "lon": float(self.lon),
            "depth_m": self.depth_m,
            "species": self.species if self.species in VALID_SPECIES else "unknown",
            "confidence": max(0.0, min(1.0, float(self.confidence))),
            "biomass_kg_est": self.biomass_kg_est,
            "sensor": self.sensor if self.sensor in VALID_SENSORS else "soundar",
            "raw_path": self.raw_path,
        }


@dataclass
class IngestReport:
    files_seen: int = 0
    rows_added: int = 0
    rows_rejected: int = 0
    errors: list[str] = field(default_factory=list)
    consolidated_total: int = 0


# ============================================================
# 1. 파일 드롭 인제스트
# ============================================================

def _normalize_frame(df: pd.DataFrame, source_path: str) -> tuple[pd.DataFrame, list[str]]:
    """업체별 columns 차이를 흡수해 표준 스키마로 통일."""
    errs: list[str] = []
    df = df.copy()

    # 흔한 변형 흡수
    rename_map = {
        "ts": "timestamp", "time": "timestamp", "datetime": "timestamp",
        "latitude": "lat", "longitude": "lon", "lng": "lon",
        "depth": "depth_m", "z": "depth_m",
        "fish_species": "species", "label": "species", "class": "species",
        "score": "confidence", "prob": "confidence",
        "biomass": "biomass_kg_est", "weight_kg": "biomass_kg_est",
        "device": "sensor", "sensor_type": "sensor",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    required = {"timestamp", "lat", "lon", "species", "confidence"}
    missing = required - set(df.columns)
    if missing:
        errs.append(f"{source_path}: 필수 컬럼 누락 {missing}")
        return pd.DataFrame(columns=DETECTION_COLS), errs

    # 누락 컬럼 채우기
    for c in DETECTION_COLS:
        if c not in df.columns:
            df[c] = pd.NA
    df["raw_path"] = df["raw_path"].fillna(source_path)
    if "mission_id" not in df.columns or df["mission_id"].isna().all():
        df["mission_id"] = Path(source_path).stem

    # 타입 강제
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    for c in ("lat", "lon", "confidence", "depth_m", "biomass_kg_est"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["species"] = df["species"].astype(str).str.strip().str.lower()
    df.loc[~df["species"].isin(VALID_SPECIES), "species"] = "unknown"
    df["sensor"] = df["sensor"].fillna("soundar").astype(str).str.strip().str.lower()
    df.loc[~df["sensor"].isin(VALID_SENSORS), "sensor"] = "soundar"
    df["confidence"] = df["confidence"].clip(0.0, 1.0)

    invalid = df["timestamp"].isna() | df["lat"].isna() | df["lon"].isna()
    if invalid.any():
        errs.append(f"{source_path}: {int(invalid.sum())}행 잘못된 시간/좌표 → 폐기")
    df = df[~invalid].copy()
    return df[DETECTION_COLS], errs


def _read_one(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"지원하지 않는 형식: {path.suffix}")


def ingest_incoming(move_processed: bool = True) -> IngestReport:
    """`artifacts/drone/incoming/` 안의 모든 파일을 읽어 표준화·중복제거 후 누적 저장."""
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
        old = pd.read_parquet(CONSOLIDATED)
        merged = pd.concat([old, new_df], ignore_index=True)
    else:
        merged = new_df

    # 중복 제거: 동일 mission·timestamp·좌표·species 면 같은 이벤트
    before = len(merged)
    merged = merged.drop_duplicates(
        subset=["mission_id", "timestamp", "lat", "lon", "species"], keep="last"
    )
    after = len(merged)
    if before != after:
        report.rows_rejected += before - after

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
# 2. 조회
# ============================================================

def load_detections(
    hours: int | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    species: str | None = None,
    min_confidence: float = 0.0,
) -> pd.DataFrame:
    """누적된 탐지 데이터 조회.

    bbox: (lat_min, lon_min, lat_max, lon_max)
    """
    if not CONSOLIDATED.exists():
        return pd.DataFrame(columns=DETECTION_COLS)
    df = pd.read_parquet(CONSOLIDATED)
    if df.empty:
        return df
    if hours is not None:
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=hours)
        df = df[df["timestamp"] >= cutoff]
    if bbox is not None:
        lat_min, lon_min, lat_max, lon_max = bbox
        df = df[(df["lat"].between(lat_min, lat_max)) &
                (df["lon"].between(lon_min, lon_max))]
    if species is not None:
        df = df[df["species"] == species]
    if min_confidence > 0:
        df = df[df["confidence"] >= min_confidence]
    return df.sort_values("timestamp").reset_index(drop=True)


def list_missions(hours: int = 168) -> pd.DataFrame:
    """최근 N시간 동안의 출항 미션 단위 요약."""
    df = load_detections(hours=hours)
    if df.empty:
        return pd.DataFrame(columns=["mission_id", "n_detections", "first_at", "last_at",
                                     "species_top", "avg_confidence"])
    g = df.groupby("mission_id")
    out = pd.DataFrame({
        "n_detections": g.size(),
        "first_at": g["timestamp"].min(),
        "last_at": g["timestamp"].max(),
        "species_top": g["species"].agg(lambda s: s.value_counts().idxmax()),
        "avg_confidence": g["confidence"].mean().round(3),
    }).reset_index().sort_values("last_at", ascending=False)
    return out


# ============================================================
# 3. 실시간 API 통합 (스텁 — PoC 후 채움)
# ============================================================

def fetch_realtime_stream(provider: str, **kwargs) -> Iterable[DroneDetection]:
    """업체별 실시간 스트림 어댑터. 미구현 — PoC 계약 후 작성."""
    raise NotImplementedError(
        f"provider='{provider}' 실시간 어댑터 미구현. "
        "현재는 ingest_incoming() 으로 파일 드롭만 지원한다. "
        "업체 결정 후 본 함수를 구현하라."
    )
