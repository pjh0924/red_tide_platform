"""모델 학습 스크립트. 합성 데이터 생성 → 통합 학습 → models/forecaster.joblib 저장."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from data_generator import generate_all_history
from model import RedTideForecaster, make_supervised
from stations import STATIONS

ARTIFACT_DIR = Path(__file__).parent / "artifacts"
ARTIFACT_DIR.mkdir(exist_ok=True)


def main(history_hours: int = 24 * 200):
    print(f"[train] 합성 데이터 생성: {len(STATIONS)}개 관측소 × {history_hours}시간")
    full = generate_all_history(hours=history_hours, seed=42)
    full.to_parquet(ARTIFACT_DIR / "history.parquet", index=False)

    print("[train] 학습 샘플 생성")
    Xs, ys = [], []
    for sid in full["station_id"].unique():
        sub = full[full["station_id"] == sid]
        X, y = make_supervised(sub)
        Xs.append(X)
        ys.append(y)
    X = pd.concat(Xs, ignore_index=True)
    y = np.vstack(ys)
    print(f"[train] X={X.shape}, y={y.shape}")

    f = RedTideForecaster().fit(X, y)
    f.save(ARTIFACT_DIR / "forecaster.joblib")
    print(f"[train] 저장 완료: {ARTIFACT_DIR / 'forecaster.joblib'}")


if __name__ == "__main__":
    main()
