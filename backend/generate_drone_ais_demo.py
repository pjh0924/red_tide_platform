"""데모 드론·AIS 데이터 생성기.

목적:
  - 실제 드론 업체 계약·AIS 라이선스 전에도 프론트엔드/모델 파이프라인을
    end-to-end 로 검증할 수 있도록 합성 데이터 1주일치를 만든다.
  - 파일 드롭 인제스트 경로(`artifacts/drone/incoming/`,
    `artifacts/ais/incoming/`)에 떨어뜨려 ingest_incoming() 으로 통합한다.

생성 규모:
  - 드론: 통영 욕지도 외해 zone, 7일치, 6시간마다 출항(28 미션), 미션당 30~80 탐지
  - AIS: 같은 zone, 7일치 어선 12척, 5분 간격 fix

실행:
    python generate_drone_ais_demo.py
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from data_pipeline.fish_grid import DEFAULT_ZONES
from fetchers import ais as ais_mod
from fetchers import drone as drone_mod

random.seed(42)
np.random.seed(42)

ZONE = DEFAULT_ZONES[0]   # yokji_offshore (통영 욕지도 외해)
NOW = datetime.now(tz=timezone.utc).replace(minute=0, second=0, microsecond=0)
DAYS = 7

LAT_MIN, LON_MIN, LAT_MAX, LON_MAX = ZONE["bbox"]

# 군집 핫스팟 3곳 — 격자 중에서 어군이 자주 나오는 좌표 (모델 학습 시 패턴 잡기 쉽도록)
HOTSPOTS = [
    (LAT_MIN + 0.6 * (LAT_MAX - LAT_MIN), LON_MIN + 0.3 * (LON_MAX - LON_MIN)),
    (LAT_MIN + 0.4 * (LAT_MAX - LAT_MIN), LON_MIN + 0.7 * (LON_MAX - LON_MIN)),
    (LAT_MIN + 0.8 * (LAT_MAX - LAT_MIN), LON_MIN + 0.5 * (LON_MAX - LON_MIN)),
]

SPECIES_DIST = ["mackerel"] * 6 + ["horse_mackerel"] * 3 + ["spanish_mackerel"] * 2 + \
               ["sardine"] * 2 + ["anchovy"] * 1 + ["unknown"] * 1


def _gen_drone_mission(start: datetime, mission_id: str) -> pd.DataFrame:
    rows = []
    n = random.randint(30, 80)
    for _ in range(n):
        # 70% 확률로 핫스팟 근처, 30% 확률로 zone 전체 균등 분포
        if random.random() < 0.7:
            cx, cy = random.choice(HOTSPOTS)
            lat = np.clip(cx + np.random.normal(0, 0.015), LAT_MIN, LAT_MAX)
            lon = np.clip(cy + np.random.normal(0, 0.015), LON_MIN, LON_MAX)
        else:
            lat = random.uniform(LAT_MIN, LAT_MAX)
            lon = random.uniform(LON_MIN, LON_MAX)
        ts = start + timedelta(seconds=random.randint(0, 3600 * 4))
        rows.append({
            "timestamp": ts.isoformat(),
            "mission_id": mission_id,
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "depth_m": round(random.uniform(8, 60), 1),
            "species": random.choice(SPECIES_DIST),
            "confidence": round(random.uniform(0.55, 0.95), 3),
            "biomass_kg_est": round(random.uniform(20, 500), 1),
            "sensor": "soundar",
        })
    return pd.DataFrame(rows)


def gen_drone_files() -> list[Path]:
    incoming = drone_mod.INCOMING_DIR
    incoming.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    n_missions = DAYS * 4   # 6시간마다 1회 = 28 미션
    for i in range(n_missions):
        start = NOW - timedelta(days=DAYS) + timedelta(hours=6 * i)
        mid = f"M{start.strftime('%Y%m%d_%H%M')}"
        df = _gen_drone_mission(start, mid)
        path = incoming / f"{mid}.csv"
        df.to_csv(path, index=False)
        paths.append(path)
    return paths


def gen_ais_file() -> Path:
    incoming = ais_mod.INCOMING_DIR
    incoming.mkdir(parents=True, exist_ok=True)
    rows = []
    n_vessels = 12
    vessel_meta = []
    for i in range(n_vessels):
        mmsi = 440000000 + i * 137
        name = f"DEMO어선{i+1:02d}"
        length = round(random.uniform(8, 30), 1)
        # 각 어선에 베이스 좌표 부여 (zone 내 분산)
        base_lat = random.uniform(LAT_MIN, LAT_MAX)
        base_lon = random.uniform(LON_MIN, LON_MAX)
        vessel_meta.append((mmsi, name, length, base_lat, base_lon))

    # 5분 간격 7일 = 2016 슬롯
    n_slots = DAYS * 24 * 12
    for slot in range(n_slots):
        ts = NOW - timedelta(days=DAYS) + timedelta(minutes=5 * slot)
        for mmsi, name, length, base_lat, base_lon in vessel_meta:
            # 랜덤 워크
            lat = base_lat + np.random.normal(0, 0.003)
            lon = base_lon + np.random.normal(0, 0.003)
            base_lat = np.clip(lat, LAT_MIN, LAT_MAX)
            base_lon = np.clip(lon, LON_MIN, LON_MAX)
            # 25% 확률로 어업 활동 속도(1~5kn), 그 외 항행 또는 정박
            r = random.random()
            if r < 0.25:
                sog = random.uniform(1, 5)
            elif r < 0.7:
                sog = random.uniform(6, 11)
            else:
                sog = random.uniform(0, 0.5)
            rows.append({
                "timestamp": ts.isoformat(),
                "mmsi": mmsi,
                "lat": round(base_lat, 6),
                "lon": round(base_lon, 6),
                "sog_kts": round(sog, 2),
                "cog_deg": round(random.uniform(0, 359.9), 1),
                "heading_deg": round(random.uniform(0, 359.9), 1),
                "nav_status": 7 if 1 <= sog <= 5 else 0,   # 7=engaged in fishing
                "vessel_type": ais_mod.VESSEL_TYPE_FISHING,
                "name": name,
                "length_m": length,
            })
    df = pd.DataFrame(rows)
    path = incoming / f"demo_ais_{NOW.strftime('%Y%m%d')}.parquet"
    df.to_parquet(path, index=False)
    return path


def main() -> None:
    print(f"[demo] zone = {ZONE['name']} ({ZONE['id']})")
    print(f"[demo] 드론 파일 생성")
    drone_paths = gen_drone_files()
    print(f"  - {len(drone_paths)} 미션 CSV → {drone_mod.INCOMING_DIR}")

    print(f"[demo] AIS 파일 생성")
    ais_path = gen_ais_file()
    print(f"  - {ais_path}")

    print("[demo] 드론 인제스트")
    rep = drone_mod.ingest_incoming(move_processed=True)
    print(f"  files={rep.files_seen} added={rep.rows_added} total={rep.consolidated_total}")

    print("[demo] AIS 인제스트")
    rep = ais_mod.ingest_incoming(move_processed=True)
    print(f"  files={rep.files_seen} added={rep.rows_added} total={rep.consolidated_total}")

    print("[demo] 완료. /api/fish/monitoring/summary 호출하면 데이터 보임.")


if __name__ == "__main__":
    main()
