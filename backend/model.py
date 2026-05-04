"""
72시간 적조 예측 모델.
- 입력: 최근 72시간의 환경/셀밀도 통계 (lag 1/3/6/12/24/48/72h, 평균/표준편차)
- 출력: 향후 72시간의 시간별 셀밀도 (log10 공간에서 회귀)
- 알고리즘: MultiOutputRegressor(GradientBoostingRegressor) — 학습 빠르고 의존성 가벼움
"""
from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.multioutput import MultiOutputRegressor
from sklearn.preprocessing import StandardScaler

LOOKBACK = 72          # 시간
HORIZON = 72           # 예측 시간
FEATURE_VARS = ["sst", "salinity", "chl_a", "din", "dip", "do", "solar", "wind", "cell_density"]
LAG_HOURS = [1, 3, 6, 12, 24, 48, 72]


def _stats_features(window: pd.DataFrame) -> dict:
    feats = {}
    for v in FEATURE_VARS:
        arr = window[v].to_numpy()
        feats[f"{v}_mean"] = float(arr.mean())
        feats[f"{v}_std"] = float(arr.std())
        feats[f"{v}_min"] = float(arr.min())
        feats[f"{v}_max"] = float(arr.max())
        for h in LAG_HOURS:
            feats[f"{v}_lag{h}"] = float(arr[-h]) if h <= len(arr) else float(arr[0])
    feats["hour"] = int(window["timestamp"].iloc[-1].hour)
    feats["doy"] = int(window["timestamp"].iloc[-1].timetuple().tm_yday)
    return feats


def make_supervised(df: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    """단일 관측소 시계열로부터 (X, y) 학습 샘플 생성."""
    df = df.sort_values("timestamp").reset_index(drop=True)
    X_rows, y_rows = [], []
    n = len(df)
    for i in range(LOOKBACK, n - HORIZON):
        window = df.iloc[i - LOOKBACK:i]
        future = df["cell_density"].iloc[i:i + HORIZON].to_numpy()
        X_rows.append(_stats_features(window))
        y_rows.append(np.log10(np.clip(future, 1.0, None)))
    return pd.DataFrame(X_rows), np.vstack(y_rows)


class RedTideForecaster:
    def __init__(self):
        self.scaler = StandardScaler()
        self.model: MultiOutputRegressor | None = None
        self.feature_columns: list[str] = []

    def fit(self, X: pd.DataFrame, y: np.ndarray):
        self.feature_columns = list(X.columns)
        Xs = self.scaler.fit_transform(X.values)
        base = GradientBoostingRegressor(
            n_estimators=120,
            max_depth=3,
            learning_rate=0.08,
            subsample=0.9,
            random_state=0,
        )
        self.model = MultiOutputRegressor(base, n_jobs=-1)
        self.model.fit(Xs, y)
        return self

    def predict(self, window: pd.DataFrame) -> np.ndarray:
        feats = _stats_features(window)
        x = np.array([[feats[c] for c in self.feature_columns]])
        xs = self.scaler.transform(x)
        log_pred = self.model.predict(xs)[0]
        return np.clip(10 ** log_pred, 0.5, 5e5)

    def save(self, path: str | Path):
        joblib.dump(
            {"scaler": self.scaler, "model": self.model, "cols": self.feature_columns},
            path,
        )

    @classmethod
    def load(cls, path: str | Path) -> "RedTideForecaster":
        obj = joblib.load(path)
        f = cls()
        f.scaler = obj["scaler"]
        f.model = obj["model"]
        f.feature_columns = obj["cols"]
        return f


def risk_level(cells_per_ml: float) -> str:
    """국내 적조 경보 기준 단순화."""
    if cells_per_ml < 100:
        return "안전"
    if cells_per_ml < 1_000:
        return "관심"
    if cells_per_ml < 10_000:
        return "주의보"
    return "경보"


def risk_color(level: str) -> str:
    return {
        "안전": "#2ecc71",
        "관심": "#f1c40f",
        "주의보": "#e67e22",
        "경보": "#e74c3c",
    }.get(level, "#95a5a6")
