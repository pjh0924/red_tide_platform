"""NIFS 전수 크롤 완료 후 정식 학습 → 모델 저장.
- 크롤 완료를 기다림 (artifacts/redtide_labels.parquet 존재)
- partial 캐시는 덮어쓰기 됨
- train_v2.main() 호출
"""
from __future__ import annotations

import time
from pathlib import Path

import train_v2

ARTIFACT = Path(__file__).parent / "artifacts"
FULL = ARTIFACT / "redtide_labels.parquet"


def main(wait_seconds: int = 600):
    t0 = time.time()
    while not FULL.exists() and time.time() - t0 < wait_seconds:
        print(f"[wait] NIFS 크롤 결과 대기... ({int(time.time()-t0)}s)", flush=True)
        time.sleep(15)
    if not FULL.exists():
        raise SystemExit(f"NIFS 결과 없음: {FULL}")

    # partial 제거 (full 사용 강제)
    partial = ARTIFACT / "redtide_labels_partial.parquet"
    if partial.exists():
        partial.unlink()
        print(f"[clean] partial 캐시 삭제: {partial}")

    print("[train] 정식 학습 시작")
    train_v2.main(start_year=2010, end_year=2025)


if __name__ == "__main__":
    main()
