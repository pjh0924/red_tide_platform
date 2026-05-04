"""v2 학습 파이프라인 (시간순 평가):
  NIFS labels + KOEM features → 광역 해역 × 일별 → 다음 1/3/7일 발생 분류기.

평가:
  1) Chronological holdout (cut_date = 2023-01-01 → 2010-2022 train / 2023-2025 test)
  2) Walk-forward CV (5 folds, expanding window)
  3) 최종 모델은 전체 데이터로 학습.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from data_pipeline.features import build_features, save_features
from data_pipeline.labels import build_daily_labels, save_daily_labels
from model_v2 import (HORIZONS, RedTideRiskModel, chronological_split,
                       make_dataset, walk_forward_splits)

ARTIFACT = Path(__file__).resolve().parent / "artifacts"
MODEL_PATH = ARTIFACT / "risk_model_v2.joblib"
REPORT_PATH = ARTIFACT / "risk_model_v2_report.json"

CUT_DATE = "2023-01-01"


def _fmt(v):
    return f"{v:.4f}" if isinstance(v, float) else str(v)


def main(start_year: int = 2010, end_year: int = 2025):
    print(f"[1] 라벨 빌드 ({start_year}~{end_year})")
    labels = build_daily_labels(start_year=start_year, end_year=end_year)
    save_daily_labels(labels)
    print(f"  rows={len(labels)}  bloom_rate={labels['bloom'].mean()*100:.2f}%  "
          f"unique regions={labels['region'].nunique()}")

    print(f"\n[2] 특성 빌드")
    feats = build_features(start_year=start_year, end_year=end_year)
    save_features(feats)
    print(f"  rows={len(feats)}  cols={len(feats.columns)}")

    print(f"\n[3] 데이터셋 생성 (horizons={HORIZONS})")
    X, y, meta, cols = make_dataset(feats, labels, horizons=HORIZONS)
    print(f"  X={X.shape}  y={y.shape}  date range {meta['date'].min().date()}~{meta['date'].max().date()}")
    print(f"  positive rate per horizon:")
    for c in y.columns:
        print(f"    {c}: {y[c].mean()*100:.2f}%")

    report = {}

    # ---- (A) Chronological holdout ----
    print(f"\n[4-A] 시간순 holdout (cut={CUT_DATE})")
    tr_idx, te_idx = chronological_split(meta, CUT_DATE)
    print(f"  train n={len(tr_idx)} ({meta['date'].iloc[tr_idx[0]].date()}~{meta['date'].iloc[tr_idx[-1]].date()})")
    print(f"  test  n={len(te_idx)} ({meta['date'].iloc[te_idx[0]].date()}~{meta['date'].iloc[te_idx[-1]].date()})")
    holdout_model = RedTideRiskModel(horizons=HORIZONS)
    holdout_report = holdout_model.fit(X, y, train_idx=tr_idx, test_idx=te_idx)
    print(f"\n  결과:")
    for h, m in holdout_report.items():
        print(f"    +{h}d  AUROC={_fmt(m['AUROC'])}  AUPRC={_fmt(m['AUPRC'])}  "
              f"Brier={_fmt(m['Brier'])}  pos_rate={_fmt(m['pos_rate'])}  n={m['n']}")
    report["holdout"] = {"cut_date": CUT_DATE, "metrics": holdout_report}

    # ---- (B) Walk-forward CV ----
    print(f"\n[4-B] Walk-forward CV (5 folds, expanding window)")
    splits = walk_forward_splits(meta, n_splits=5, min_train_years=5)
    print(f"  fold 수: {len(splits)}")
    cv_model = RedTideRiskModel(horizons=HORIZONS)
    cv_report = cv_model.cross_validate(X, y, splits)
    cv_summary = {}
    for h, folds in cv_report.items():
        aurocs = [f["AUROC"] for f in folds if f["AUROC"] is not None]
        auprcs = [f["AUPRC"] for f in folds if f["AUPRC"] is not None]
        briers = [f["Brier"] for f in folds]
        mean_auroc = float(np.mean(aurocs)) if aurocs else None
        mean_auprc = float(np.mean(auprcs)) if auprcs else None
        std_auroc = float(np.std(aurocs)) if aurocs else None
        cv_summary[h] = {
            "mean_AUROC": mean_auroc, "std_AUROC": std_auroc,
            "mean_AUPRC": mean_auprc, "mean_Brier": float(np.mean(briers)),
            "folds": folds,
        }
        print(f"    +{h}d  mean AUROC={_fmt(mean_auroc)} ± {_fmt(std_auroc)}  "
              f"mean AUPRC={_fmt(mean_auprc)}  mean Brier={_fmt(float(np.mean(briers)))}")
    report["walk_forward_cv"] = cv_summary

    # ---- (C) 최종: 전체 데이터로 학습 → 저장 ----
    print(f"\n[5] 최종 모델 (전체 데이터 학습)")
    final = RedTideRiskModel(horizons=HORIZONS)
    final.fit(X, y)  # train_idx/test_idx 없이 → 전체 학습, 평가 생략
    final.save(MODEL_PATH)
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    print(f"  저장: {MODEL_PATH}")
    print(f"  리포트: {REPORT_PATH}")


if __name__ == "__main__":
    main()
