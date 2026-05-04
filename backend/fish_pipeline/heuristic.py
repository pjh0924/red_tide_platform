"""환경 변수 → 어종 출현 적합도 점수 (heuristic).

원리: 각 어종 알려진 최적 수온/염분 가우시안 + 월별 가중치.
score = exp(-(sst-c)²/2σ²) × exp(-(sal-c)²/2σ²) × month_weight
출력: 0~1 정규화된 출현 확률 (확률 의미보다 "적합도 점수" 로 해석).

향후 KOSIS 어획 라벨 확보 시:
  → species_probability_ml(env, species_id) 로 교체. 인터페이스는 동일.
"""
from __future__ import annotations

import math
from datetime import date

from .species import SPECIES, get_species

# month_weight 의 최댓값으로 정규화하기 위해 미리 계산
_MAX_MONTH_WEIGHT = {s["id"]: max(s["month_weight"]) for s in SPECIES}


def _gaussian(x: float, center: float, sigma: float) -> float:
    return math.exp(-((x - center) ** 2) / (2 * sigma ** 2))


def species_probability(species_id: str, sst: float | None,
                        salinity: float | None, month: int) -> float:
    sp = get_species(species_id)
    if sp is None:
        return 0.0
    if sst is None or salinity is None:
        return 0.0
    sst_score = _gaussian(sst, sp["sst_center"], sp["sst_sigma"])
    sal_score = _gaussian(salinity, sp["sal_center"], sp["sal_sigma"])
    m_idx = max(1, min(12, int(month))) - 1
    month_score = sp["month_weight"][m_idx] / _MAX_MONTH_WEIGHT[sp["id"]]
    return float(max(0.0, min(1.0, sst_score * sal_score * month_score)))


def all_species_probabilities(sst: float | None, salinity: float | None,
                              month: int) -> dict[str, float]:
    """모든 어종에 대한 출현 확률 dict."""
    return {sp["id"]: species_probability(sp["id"], sst, salinity, month)
            for sp in SPECIES}


def seasonal_curve(species_id: str, sst_year: list[float],
                   salinity_year: list[float]) -> list[float]:
    """월별 (1~12) 출현 확률 곡선. sst/sal 가 12개씩 들어와야 함."""
    if len(sst_year) != 12 or len(salinity_year) != 12:
        raise ValueError("sst_year, salinity_year 길이는 12 (월별)")
    return [species_probability(species_id, sst_year[m], salinity_year[m], m + 1)
            for m in range(12)]


def fish_risk_level(p: float) -> str:
    """출현 확률 → 등급 (어획 의사결정용)."""
    if p < 0.1:  return "희박"
    if p < 0.3:  return "낮음"
    if p < 0.6:  return "보통"
    if p < 0.8:  return "높음"
    return "매우 높음"


def fish_risk_color(p: float) -> str:
    if p < 0.1:  return "#7f8c8d"
    if p < 0.3:  return "#bdc3c7"
    if p < 0.6:  return "#3498db"
    if p < 0.8:  return "#1abc9c"
    return "#27ae60"
