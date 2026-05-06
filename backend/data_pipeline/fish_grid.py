"""시간별 어군 밀도 라벨 빌더.

목적:
  - 드론 탐지 + AIS 어업 추정을 1km 격자 × 시간 단위로 집계해
    ML 학습용 라벨/특성을 생성한다.
  - 어군 출현 예측 모델(v3)의 ground truth 가 된다.

격자 정의:
  - 본 사업 PoC 어장(예: 통영 욕지도 외해)을 bbox 로 지정.
  - 위도 1° = 약 111km, 경도 1° = 약 91km(위도 35°N 기준).
    1km 격자 ≈ lat 0.009°, lon 0.011°.
  - 격자 ID: f'{lat_idx:04d}_{lon_idx:04d}' (bbox 좌하단 기준 정수 인덱스).

라벨 정의:
  per (cell, hour):
    drone_detection_count    드론 탐지 이벤트 수
    drone_avg_confidence     평균 신뢰도
    drone_total_biomass_kg   추정 바이오매스 합 (NaN 가능)
    species_top              가장 많이 탐지된 어종
    ais_fishing_vessels      어업 활동 추정 어선 수 (sog 1~5kn)
    ais_dwell_minutes_est    어선이 어업 활동에 머문 시간 추정
    fish_density_score       0~1 정규화 점수 (드론 + AIS 합성)

다음 단계: 본 결과 + 환경 features 를 결합해 model_v3 학습.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from fetchers import ais, drone

ARTIFACT_DIR = Path(__file__).parent.parent / "artifacts"
DENSITY_PATH = ARTIFACT_DIR / "fish_density_hourly.parquet"

# 본 사업 1차 PoC 어장 (통영 욕지도 외해 — 적조 빈발 + 어업 활성)
DEFAULT_ZONES: list[dict] = [
    {
        "id": "yokji_offshore",
        "name": "통영 욕지도 외해",
        "region": "경남중부",
        "bbox": (34.55, 128.20, 34.78, 128.55),  # (lat_min, lon_min, lat_max, lon_max)
    },
    {
        "id": "namhae_mijo",
        "name": "남해 미조 외해",
        "region": "경남서부",
        "bbox": (34.55, 127.80, 34.78, 128.10),
    },
    {
        "id": "geoje_maemul",
        "name": "거제 매물도 외해",
        "region": "경남중부",
        "bbox": (34.55, 128.55, 34.78, 128.85),
    },
]

# 1km 격자 변환 상수 (위도 35°N 기준)
DEG_LAT_PER_KM = 1.0 / 111.0
DEG_LON_PER_KM = 1.0 / 91.0


@dataclass(frozen=True)
class Zone:
    id: str
    name: str
    region: str
    bbox: tuple[float, float, float, float]   # lat_min, lon_min, lat_max, lon_max

    @property
    def lat_min(self) -> float: return self.bbox[0]
    @property
    def lon_min(self) -> float: return self.bbox[1]
    @property
    def lat_max(self) -> float: return self.bbox[2]
    @property
    def lon_max(self) -> float: return self.bbox[3]


def get_zone(zone_id: str) -> Zone:
    for z in DEFAULT_ZONES:
        if z["id"] == zone_id:
            return Zone(**z)
    raise KeyError(f"unknown zone: {zone_id}")


def list_zones() -> list[Zone]:
    return [Zone(**z) for z in DEFAULT_ZONES]


# ============================================================
# 격자 유틸
# ============================================================

def latlon_to_cell(lat: float, lon: float, zone: Zone,
                   cell_km: float = 1.0) -> tuple[int, int] | None:
    """좌표 → (lat_idx, lon_idx). bbox 밖이면 None."""
    if not (zone.lat_min <= lat <= zone.lat_max and zone.lon_min <= lon <= zone.lon_max):
        return None
    lat_idx = int((lat - zone.lat_min) / (DEG_LAT_PER_KM * cell_km))
    lon_idx = int((lon - zone.lon_min) / (DEG_LON_PER_KM * cell_km))
    return lat_idx, lon_idx


def cell_to_center(lat_idx: int, lon_idx: int, zone: Zone,
                   cell_km: float = 1.0) -> tuple[float, float]:
    lat = zone.lat_min + (lat_idx + 0.5) * DEG_LAT_PER_KM * cell_km
    lon = zone.lon_min + (lon_idx + 0.5) * DEG_LON_PER_KM * cell_km
    return lat, lon


def grid_size(zone: Zone, cell_km: float = 1.0) -> tuple[int, int]:
    """(n_lat, n_lon) 격자 수."""
    n_lat = int(math.ceil((zone.lat_max - zone.lat_min) / (DEG_LAT_PER_KM * cell_km)))
    n_lon = int(math.ceil((zone.lon_max - zone.lon_min) / (DEG_LON_PER_KM * cell_km)))
    return n_lat, n_lon


def _cell_id(lat_idx: int, lon_idx: int) -> str:
    return f"{lat_idx:04d}_{lon_idx:04d}"


# ============================================================
# 시간별 밀도 빌더
# ============================================================

def build_hourly_density(
    zone: Zone | str,
    hours: int = 168,
    cell_km: float = 1.0,
    save: bool = True,
) -> pd.DataFrame:
    """zone 안의 모든 1km 격자 × 시간 슬롯에 대한 밀도 라벨 생성.

    AIS·드론 데이터가 비어 있으면 모든 라벨이 0인 빈 격자만 반환.
    """
    if isinstance(zone, str):
        zone = get_zone(zone)
    zone_obj = zone

    drone_df = drone.load_detections(hours=hours, bbox=zone_obj.bbox)
    ais_df = ais.estimate_fishing_activity(
        ais.load_fixes(hours=hours, bbox=zone_obj.bbox, fishing_only=True)
    )

    # 시간 버킷
    cutoff = pd.Timestamp.now(tz="UTC").floor("h") - pd.Timedelta(hours=hours)
    end = pd.Timestamp.now(tz="UTC").floor("h")
    hours_index = pd.date_range(cutoff, end, freq="h", tz="UTC", inclusive="left")

    # 격자 ID 부여
    def _attach_cell(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            df = df.copy()
            df["cell_lat_idx"] = pd.Series(dtype="Int64")
            df["cell_lon_idx"] = pd.Series(dtype="Int64")
            df["cell_id"] = pd.Series(dtype="string")
            df["hour"] = pd.Series(dtype="datetime64[ns, UTC]")
            return df
        df = df.copy()
        cells = df.apply(
            lambda r: latlon_to_cell(r["lat"], r["lon"], zone_obj, cell_km),
            axis=1,
        )
        df["cell_lat_idx"] = [c[0] if c else None for c in cells]
        df["cell_lon_idx"] = [c[1] if c else None for c in cells]
        df = df.dropna(subset=["cell_lat_idx", "cell_lon_idx"]).copy()
        df["cell_lat_idx"] = df["cell_lat_idx"].astype(int)
        df["cell_lon_idx"] = df["cell_lon_idx"].astype(int)
        df["cell_id"] = [
            _cell_id(la, lo) for la, lo in zip(df["cell_lat_idx"], df["cell_lon_idx"])
        ]
        df["hour"] = pd.to_datetime(df["timestamp"], utc=True).dt.floor("h")
        return df

    drone_c = _attach_cell(drone_df)
    ais_c = _attach_cell(ais_df)

    # 드론 집계
    if not drone_c.empty:
        gd = drone_c.groupby(["cell_id", "hour"], as_index=False).agg(
            cell_lat_idx=("cell_lat_idx", "first"),
            cell_lon_idx=("cell_lon_idx", "first"),
            drone_detection_count=("species", "size"),
            drone_avg_confidence=("confidence", "mean"),
            drone_total_biomass_kg=("biomass_kg_est", "sum"),
            species_top=("species", lambda s: s.value_counts().idxmax()),
        )
    else:
        gd = pd.DataFrame(columns=["cell_id", "hour", "cell_lat_idx", "cell_lon_idx",
                                   "drone_detection_count", "drone_avg_confidence",
                                   "drone_total_biomass_kg", "species_top"])

    # AIS 집계
    if not ais_c.empty:
        ga = ais_c.groupby(["cell_id", "hour"], as_index=False).agg(
            cell_lat_idx=("cell_lat_idx", "first"),
            cell_lon_idx=("cell_lon_idx", "first"),
            ais_fishing_vessels=("mmsi", "nunique"),
            ais_fix_count=("mmsi", "size"),
        )
        ga["ais_dwell_minutes_est"] = ga["ais_fix_count"] * 5  # 5분 간격 가정
    else:
        ga = pd.DataFrame(columns=["cell_id", "hour", "cell_lat_idx", "cell_lon_idx",
                                   "ais_fishing_vessels", "ais_fix_count",
                                   "ais_dwell_minutes_est"])

    # 외부 조인 (드론·AIS 어느 쪽이라도 있으면 격자 등재)
    merged = pd.merge(gd, ga, on=["cell_id", "hour", "cell_lat_idx", "cell_lon_idx"],
                      how="outer")
    if merged.empty:
        # 빈 결과: 격자/시간 cross join 만 만들고 모두 0으로 채움
        n_lat, n_lon = grid_size(zone_obj, cell_km)
        ids = [_cell_id(la, lo) for la in range(n_lat) for lo in range(n_lon)]
        merged = pd.DataFrame({"cell_id": ids})
        merged["hour"] = end - pd.Timedelta(hours=1)  # 단일 슬롯
        merged["cell_lat_idx"] = [int(c.split("_")[0]) for c in merged["cell_id"]]
        merged["cell_lon_idx"] = [int(c.split("_")[1]) for c in merged["cell_id"]]

    # 결측치 채우기
    for c in ("drone_detection_count", "drone_avg_confidence", "drone_total_biomass_kg",
              "ais_fishing_vessels", "ais_fix_count", "ais_dwell_minutes_est"):
        if c in merged.columns:
            merged[c] = merged[c].fillna(0)
    if "species_top" not in merged.columns:
        merged["species_top"] = "unknown"
    merged["species_top"] = merged["species_top"].fillna("unknown")

    # 격자 중심 좌표
    centers = merged.apply(
        lambda r: cell_to_center(int(r["cell_lat_idx"]), int(r["cell_lon_idx"]),
                                 zone_obj, cell_km),
        axis=1,
    )
    merged["center_lat"] = [c[0] for c in centers]
    merged["center_lon"] = [c[1] for c in centers]

    # 합성 밀도 점수 (0~1)
    # 드론 신호: 탐지수×신뢰도, AIS 신호: 어업 어선수×체류시간.
    # 각각 z-score 후 sigmoid 합성 — 데이터 적을 때도 안정적.
    drone_signal = (merged.get("drone_detection_count", 0).astype(float) *
                    merged.get("drone_avg_confidence", 0).astype(float))
    ais_signal = (merged.get("ais_fishing_vessels", 0).astype(float) *
                  np.log1p(merged.get("ais_dwell_minutes_est", 0).astype(float)))

    def _norm(s: pd.Series) -> pd.Series:
        if s.std() < 1e-9:
            return s * 0.0
        return (s - s.mean()) / s.std()

    score = 0.6 * _norm(drone_signal) + 0.4 * _norm(ais_signal)
    merged["fish_density_score"] = (1 / (1 + np.exp(-score))).round(4)

    merged["zone_id"] = zone_obj.id
    merged["zone_name"] = zone_obj.name
    merged["region"] = zone_obj.region

    out_cols = [
        "zone_id", "zone_name", "region", "hour", "cell_id",
        "cell_lat_idx", "cell_lon_idx", "center_lat", "center_lon",
        "drone_detection_count", "drone_avg_confidence", "drone_total_biomass_kg",
        "species_top",
        "ais_fishing_vessels", "ais_dwell_minutes_est",
        "fish_density_score",
    ]
    out = merged[[c for c in out_cols if c in merged.columns]].copy()
    out = out.sort_values(["hour", "cell_id"]).reset_index(drop=True)

    if save:
        DENSITY_PATH.parent.mkdir(parents=True, exist_ok=True)
        # zone 별로 파일 분리: <zone_id>_density.parquet
        path = DENSITY_PATH.parent / f"fish_density_{zone_obj.id}.parquet"
        out.to_parquet(path, index=False)
    return out


def latest_density_grid(zone_id: str = "yokji_offshore",
                        cell_km: float = 1.0) -> pd.DataFrame:
    """가장 최근 1시간의 격자별 밀도 (대시보드용)."""
    zone = get_zone(zone_id)
    df = build_hourly_density(zone, hours=2, cell_km=cell_km, save=False)
    if df.empty:
        return df
    last_hour = df["hour"].max()
    return df[df["hour"] == last_hour].reset_index(drop=True)
