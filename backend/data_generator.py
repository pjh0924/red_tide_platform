"""
적조 환경 데이터 시뮬레이터.
실제 환경 변수 (수온/염분/영양염/일사량 등)와 코클로디니움 셀 밀도 사이의
경험적 관계를 단순화하여 합성 시계열을 생성한다.
실 운영시 국립수산과학원 종합정보시스템(NIFS) 또는 해양환경공단 API로 교체.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from stations import STATIONS


@dataclass
class EnvSnapshot:
    timestamp: datetime
    station_id: str
    sst: float           # 표층수온 (°C)
    salinity: float      # 염분 (psu)
    chl_a: float         # 클로로필-a (µg/L)
    din: float           # 용존무기질소 (µM)
    dip: float           # 용존무기인 (µM)
    do: float            # 용존산소 (mg/L)
    solar: float         # 일사량 (MJ/m²)
    wind: float          # 풍속 (m/s)
    cell_density: float  # Cochlodinium polykrikoides (cells/mL)


def _seasonal(t: datetime, base: float, amp: float, peak_doy: int = 220) -> float:
    """연주기 변동 (peak_doy 기준 sine)."""
    doy = t.timetuple().tm_yday
    return base + amp * math.sin(2 * math.pi * (doy - peak_doy + 91.25) / 365.25)


def _diurnal(t: datetime, base: float, amp: float, peak_hour: int = 14) -> float:
    """일주기 변동."""
    return base + amp * math.sin(2 * math.pi * (t.hour - peak_hour + 6) / 24)


def _region_bias(region: str) -> dict:
    """해역별 환경 편차."""
    biases = {
        "남해": {"sst": +1.5, "chl": +1.2, "nutrient": +1.0, "risk": 1.6},
        "동남해": {"sst": +0.8, "chl": +0.6, "nutrient": +0.6, "risk": 1.1},
        "동해": {"sst": -1.0, "chl": -0.3, "nutrient": -0.4, "risk": 0.5},
        "서남해": {"sst": +0.5, "chl": +0.4, "nutrient": +0.7, "risk": 0.8},
        "서해": {"sst": -0.5, "chl": +0.2, "nutrient": +0.3, "risk": 0.4},
        "제주": {"sst": +2.0, "chl": +0.3, "nutrient": -0.2, "risk": 0.7},
    }
    return biases.get(region, {"sst": 0, "chl": 0, "nutrient": 0, "risk": 1.0})


def _bloom_pressure(sst: float, salinity: float, chl_a: float,
                    din: float, dip: float, solar: float, wind: float,
                    region_risk: float) -> float:
    """
    환경 → 적조 발생 가능성 점수 (0~1).
    Cochlodinium polykrikoides 알려진 최적조건:
      수온 22~28°C, 염분 28~33 psu, 강한 일사, 약한 바람(저혼합)
    """
    f_sst = math.exp(-((sst - 25.0) ** 2) / (2 * 3.0 ** 2))
    f_sal = math.exp(-((salinity - 30.5) ** 2) / (2 * 1.8 ** 2))
    f_nut = 1.0 - math.exp(-(din / 5.0 + dip / 0.5))
    f_chl = min(chl_a / 12.0, 1.5)
    f_solar = min(solar / 22.0, 1.2)
    f_wind = math.exp(-((wind - 2.0) ** 2) / (2 * 4.0 ** 2))
    score = f_sst * f_sal * f_nut * f_chl * f_solar * f_wind * region_risk
    return float(np.clip(score, 0.0, 1.0))


def _cell_density_from_score(score: float, prev: float, rng: np.random.Generator) -> float:
    """점수와 이전 셀 밀도로부터 다음 셀 밀도 산출 (지수 성장/감쇠 모델)."""
    growth = (score - 0.35) * 0.9
    noise = rng.normal(0, 0.25)
    next_log = math.log(max(prev, 1.0)) + growth + noise
    return float(np.clip(math.exp(next_log), 0.5, 5e5))


def generate_history(station: dict, hours: int = 24 * 60,
                     end: datetime | None = None,
                     seed: int | None = None) -> pd.DataFrame:
    """단일 관측소의 과거 시계열 합성."""
    end = end or datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=hours - 1)
    rng = np.random.default_rng(seed if seed is not None else hash(station["id"]) & 0xFFFFFFFF)

    bias = _region_bias(station["region"])
    times = [start + timedelta(hours=i) for i in range(hours)]
    rows = []
    cell = rng.uniform(5, 80)

    for t in times:
        sst = _seasonal(t, base=15.0 + bias["sst"], amp=9.0) + _diurnal(t, 0, 0.6) + rng.normal(0, 0.4)
        sal = 31.5 + 0.8 * math.sin(2 * math.pi * t.timetuple().tm_yday / 365.25) + rng.normal(0, 0.35)
        solar = max(0.0, _diurnal(t, base=12, amp=14, peak_hour=13)) * (0.4 + 0.6 * (1 if 5 <= t.hour <= 19 else 0))
        wind = max(0.5, 4.0 + 2.5 * rng.standard_normal())
        din = max(0.1, 4.0 + bias["nutrient"] * 2 + rng.normal(0, 1.5))
        dip = max(0.02, 0.4 + bias["nutrient"] * 0.2 + rng.normal(0, 0.15))
        chl_a = max(0.1, 2.5 + bias["chl"] + 0.0008 * cell + rng.normal(0, 0.6))
        do = max(2.0, 8.5 - 0.15 * (sst - 15) + rng.normal(0, 0.3))

        score = _bloom_pressure(sst, sal, chl_a, din, dip, solar, wind, bias["risk"])
        cell = _cell_density_from_score(score, cell, rng)

        rows.append({
            "timestamp": t,
            "station_id": station["id"],
            "sst": round(sst, 2),
            "salinity": round(sal, 2),
            "chl_a": round(chl_a, 2),
            "din": round(din, 2),
            "dip": round(dip, 3),
            "do": round(do, 2),
            "solar": round(solar, 2),
            "wind": round(wind, 2),
            "cell_density": round(cell, 1),
        })
    return pd.DataFrame(rows)


def generate_all_history(hours: int = 24 * 60, seed: int = 42) -> pd.DataFrame:
    frames = [generate_history(s, hours=hours, seed=seed + i) for i, s in enumerate(STATIONS)]
    return pd.concat(frames, ignore_index=True)
