"""
NIFS 적조속보 → 광역 해역 × 일별 라벨.

라벨 정의:
  - 발생 (binary): 그 해역/그 날 NIFS 게시글에 등재되었으면 1, 아니면 0
  - 위험도 (continuous): density_max 의 log10. 미보고 0 → 0, 1만 cells/mL → 6
  - 단계 (categorical): 셀밀도 기준 안전/관심/주의보/경보
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from .regions import REGIONS, map_to_region

ARTIFACT = Path(__file__).resolve().parent.parent / "artifacts"
RAW = ARTIFACT / "redtide_labels.parquet"
RAW_PARTIAL = ARTIFACT / "redtide_labels_partial.parquet"
DAILY = ARTIFACT / "labels_daily.parquet"


def _resolve_raw() -> Path:
    """전체 크롤 결과가 있으면 우선, 없으면 partial 사용."""
    if RAW.exists():
        return RAW
    if RAW_PARTIAL.exists():
        return RAW_PARTIAL
    raise FileNotFoundError(
        f"NIFS 크롤 결과 없음: {RAW} 또는 {RAW_PARTIAL}\n"
        f"`python crawl_nifs_full.py` 실행."
    )


def risk_level(cells: float) -> str:
    if pd.isna(cells) or cells < 100:
        return "안전"
    if cells < 1_000:
        return "관심"
    if cells < 10_000:
        return "주의보"
    return "경보"


def build_daily_labels(start_year: int = 2010,
                       end_year: int = 2025) -> pd.DataFrame:
    """NIFS raw → (region, date) 인덱스의 일별 라벨 데이터프레임.
    NIFS 미게재 일은 음성 라벨(0)로 채움.
    """
    raw = pd.read_parquet(_resolve_raw())
    raw["posted"] = pd.to_datetime(raw["posted"], errors="coerce")
    raw = raw.dropna(subset=["posted"])
    raw["region"] = raw["region"].apply(map_to_region)
    raw = raw.dropna(subset=["region"])
    raw["date"] = raw["posted"].dt.normalize().astype("datetime64[ns]")

    # 동일 (region, date) 에 여러 종/관측 → 셀밀도 max 채택
    g = raw.groupby(["region", "date"], as_index=False).agg(
        density_max=("density_max", "max"),
        density_min=("density_min", "min"),
        sst_max=("sst_max", "max"),
        sst_min=("sst_min", "min"),
        sal_max=("sal_max", "max"),
        sal_min=("sal_min", "min"),
        n_records=("region", "size"),
    )
    g["bloom"] = 1
    g["risk_score"] = np.log10(np.clip(g["density_max"].fillna(100.0), 1, None))
    g["level"] = g["density_max"].apply(risk_level)

    # 광역 해역 × 일자 풀 그리드 생성, 미게재 일은 0
    start = date(start_year, 1, 1)
    end = date(end_year, 12, 31)
    all_dates = pd.date_range(start, end, freq="D")
    grid = pd.MultiIndex.from_product(
        [REGIONS, all_dates], names=["region", "date"]
    ).to_frame(index=False)
    out = grid.merge(g, on=["region", "date"], how="left")
    out["bloom"] = out["bloom"].fillna(0).astype(int)
    out["risk_score"] = out["risk_score"].fillna(0.0)
    out["level"] = out["level"].fillna("안전")
    out["n_records"] = out["n_records"].fillna(0).astype(int)
    return out


def save_daily_labels(df: pd.DataFrame) -> Path:
    DAILY.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(DAILY, index=False)
    return DAILY
