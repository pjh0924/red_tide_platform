"""
적조예측 v2 모델: 광역 해역 × 일별 데이터로 다음 N일 발생 확률 예측.
- 입력: KOEM (수온/염분/영양염/클로로필) + 계절 + rolling
- 출력: 향후 1일, 3일, 7일 적조 발생 확률 (multi-output classifier)
- 알고리즘: HistGradientBoosting (월단위 측정 + 미세결측 강함)
- 평가: 시간순 holdout + walk-forward CV (시간 누설 방지)
"""
from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import (average_precision_score, brier_score_loss,
                             roc_auc_score)

from data_pipeline.features import ASOS_VARS, NEMO_VARS, SAT_VARS

HORIZONS = [1, 3, 7]   # 일 단위. 72h ≈ 3일
ARTIFACT = Path(__file__).resolve().parent / "artifacts"


def _build_targets(labels: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    """각 (region, date) 에 대해 다음 h일 안에 발생이 있으면 1.
    raw labels의 미래 bloom 을 보는 것은 지도학습의 정의이지 leakage 가 아님.
    """
    out = labels[["region", "date", "bloom"]].copy()
    out = out.sort_values(["region", "date"])
    for h in horizons:
        out[f"y_{h}d"] = (
            out.groupby("region")["bloom"]
            .transform(lambda s: s[::-1].rolling(h, min_periods=1).max()[::-1].shift(-1).fillna(0))
            .astype(int)
        )
    return out


def make_dataset(features: pd.DataFrame, labels: pd.DataFrame,
                 horizons: list[int] = HORIZONS) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    """returns (X, y, meta, feature_cols). meta has region, date columns."""
    targets = _build_targets(labels, horizons)
    df = features.merge(targets, on=["region", "date"], how="inner")
    df = df.dropna(subset=NEMO_VARS, how="all").sort_values(["date", "region"])

    base_vars = NEMO_VARS + [v for v in ASOS_VARS + SAT_VARS if v in df.columns]
    feature_cols = (
        base_vars
        + [f"{v}_r7" for v in base_vars if f"{v}_r7" in df.columns]
        + [f"{v}_r30" for v in base_vars if f"{v}_r30" in df.columns]
        + ["doy_sin", "doy_cos", "month"]
    )
    feature_cols = [c for c in feature_cols if c in df.columns]
    X = df[feature_cols].reset_index(drop=True)
    y = df[[f"y_{h}d" for h in horizons]].reset_index(drop=True)
    meta = df[["region", "date"]].reset_index(drop=True)
    return X, y, meta, feature_cols


def chronological_split(meta: pd.DataFrame, cut_date: str) -> tuple[np.ndarray, np.ndarray]:
    """meta['date'] 기준으로 cut_date 이전=train, 이후=test."""
    cut = pd.Timestamp(cut_date)
    train_idx = np.where(meta["date"] < cut)[0]
    test_idx = np.where(meta["date"] >= cut)[0]
    return train_idx, test_idx


def walk_forward_splits(meta: pd.DataFrame, n_splits: int = 5,
                        min_train_years: int = 5) -> list[tuple[np.ndarray, np.ndarray]]:
    """누적 walk-forward (expanding window) 시간순 CV.
    예: years=[2010..2025], n_splits=5 → 각 fold:
      fold k: train=[전체 시작 ~ test 시작 -1], test=다음 ~years/n_splits 년치
    """
    dates = meta["date"]
    yr_min = int(dates.dt.year.min())
    yr_max = int(dates.dt.year.max())
    train_start = yr_min + min_train_years - 1
    if train_start >= yr_max:
        return []
    fold_years = max(1, (yr_max - train_start) // n_splits)
    splits = []
    for k in range(n_splits):
        cut_train_end = train_start + k * fold_years
        cut_test_end = cut_train_end + fold_years
        train_mask = dates.dt.year <= cut_train_end
        test_mask = (dates.dt.year > cut_train_end) & (dates.dt.year <= cut_test_end)
        if test_mask.sum() == 0 or train_mask.sum() == 0:
            continue
        splits.append((np.where(train_mask)[0], np.where(test_mask)[0]))
    return splits


def _evaluate(clf, X, y) -> dict:
    if y.sum() == 0:
        return {"AUROC": None, "AUPRC": None, "Brier": float(brier_score_loss(y, clf.predict_proba(X)[:, 1])),
                "pos_rate": 0.0, "n": int(len(y))}
    proba = clf.predict_proba(X)[:, 1]
    return {
        "AUROC": float(roc_auc_score(y, proba)),
        "AUPRC": float(average_precision_score(y, proba)),
        "Brier": float(brier_score_loss(y, proba)),
        "pos_rate": float(y.mean()),
        "n": int(len(y)),
    }


class RedTideRiskModel:
    def __init__(self, horizons: list[int] = HORIZONS):
        self.horizons = horizons
        self.models: dict[int, HistGradientBoostingClassifier] = {}
        self.feature_cols: list[str] = []

    @staticmethod
    def _new_clf() -> HistGradientBoostingClassifier:
        return HistGradientBoostingClassifier(
            max_iter=300, max_depth=6, learning_rate=0.05,
            class_weight="balanced", random_state=0,
        )

    def fit(self, X: pd.DataFrame, y: pd.DataFrame,
            train_idx: np.ndarray | None = None,
            test_idx: np.ndarray | None = None) -> dict:
        """train_idx/test_idx 가 주어지면 시간순 holdout. 없으면 전체로 학습 + 평가 생략."""
        self.feature_cols = list(X.columns)
        Xv = X.values
        report: dict = {}
        for h in self.horizons:
            col = f"y_{h}d"
            clf = self._new_clf()
            yv = y[col].values
            if train_idx is not None and test_idx is not None:
                clf.fit(Xv[train_idx], yv[train_idx])
                report[h] = _evaluate(clf, Xv[test_idx], yv[test_idx])
            else:
                clf.fit(Xv, yv)
                report[h] = {"AUROC": None, "n_train": int(len(yv)), "pos_rate": float(yv.mean())}
            self.models[h] = clf
        return report

    def cross_validate(self, X: pd.DataFrame, y: pd.DataFrame,
                        splits: list[tuple[np.ndarray, np.ndarray]]) -> dict:
        """walk-forward CV 평가 (학습 결과는 self.models 에 저장하지 않음)."""
        Xv = X.values
        out: dict = {}
        for h in self.horizons:
            col = f"y_{h}d"
            yv = y[col].values
            fold_results = []
            for k, (tr, te) in enumerate(splits):
                clf = self._new_clf()
                clf.fit(Xv[tr], yv[tr])
                m = _evaluate(clf, Xv[te], yv[te])
                m["fold"] = k
                m["n_train"] = int(len(tr))
                fold_results.append(m)
            out[h] = fold_results
        return out

    def predict_proba(self, X: pd.DataFrame) -> dict[int, np.ndarray]:
        Xv = X[self.feature_cols].values
        return {h: m.predict_proba(Xv)[:, 1] for h, m in self.models.items()}

    def save(self, path: str | Path):
        joblib.dump(
            {"models": self.models, "horizons": self.horizons, "cols": self.feature_cols},
            path,
        )

    @classmethod
    def load(cls, path: str | Path) -> "RedTideRiskModel":
        obj = joblib.load(path)
        m = cls(horizons=obj["horizons"])
        m.models = obj["models"]
        m.feature_cols = obj["cols"]
        return m


def risk_color(p: float) -> str:
    if p < 0.1:  return "#2ecc71"
    if p < 0.3:  return "#f1c40f"
    if p < 0.6:  return "#e67e22"
    return "#e74c3c"


def risk_level(p: float) -> str:
    if p < 0.1:  return "안전"
    if p < 0.3:  return "관심"
    if p < 0.6:  return "주의보"
    return "경보"
