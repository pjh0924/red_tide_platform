"""원클릭 데이터 수집 + 학습 스크립트.

사용:
  1) backend/.env 에 API 키 입력 (DATA_GO_KR_KEY, KMA_API_KEY,
     COPERNICUS_USERNAME, COPERNICUS_PASSWORD)
  2) python setup_data.py

artifacts/ 폴더에 모든 데이터/모델 생성. 이미 존재하는 단계는 자동 skip.
총 소요시간: 처음 실행 시 약 20~30분 (NIFS 크롤링이 가장 길다).
"""
from __future__ import annotations

import sys
from pathlib import Path

import config

ARTIFACT = Path(__file__).parent / "artifacts"
ARTIFACT.mkdir(exist_ok=True)


def step(name: str, target: Path, fn, force: bool = False):
    if not force and target.exists():
        print(f"  · skip {name} (이미 있음: {target.name})")
        return
    print(f"  · {name} 시작...", flush=True)
    fn()
    print(f"    → {target.name} 생성 완료", flush=True)


def main(force: bool = False):
    if not config.DATA_GO_KR_KEY:
        sys.exit("[!] DATA_GO_KR_KEY 미설정. backend/.env 를 확인하세요.")

    print("=" * 60)
    print("적조예측 플랫폼 — 데이터/모델 setup")
    print("=" * 60)

    # 1) KOEM 측정값 (남해)
    print("\n[1/6] KOEM 측정망 측정값 (남해)")
    def _koem():
        import fetch_koem_full
        fetch_koem_full.main()
    step("KOEM 남해 다운로드", ARTIFACT / "koem_nemo.parquet", _koem, force)

    # 2) NIFS 적조속보 크롤링
    print("\n[2/6] NIFS 적조속보 크롤링 (~10분)")
    def _nifs():
        import crawl_nifs_full
        crawl_nifs_full.main(max_pages=130)
    step("NIFS 전수 크롤", ARTIFACT / "redtide_labels.parquet", _nifs, force)

    # 3) KMA ASOS 일자료
    print("\n[3/6] KMA ASOS 일자료 (경남 3 지점 × 16년)")
    def _asos():
        import fetch_asos_history
        fetch_asos_history.main()
    if not config.KMA_API_KEY:
        print("  · skip ASOS (KMA_API_KEY 미설정)")
    else:
        step("ASOS 일자료", ARTIFACT / "asos_daily.parquet", _asos, force)

    # 4) Copernicus 위성 chl-a (선택)
    print("\n[4/6] Copernicus Sentinel chl-a (선택)")
    if not (config.COPERNICUS_USERNAME and config.COPERNICUS_PASSWORD):
        print("  · skip 위성 chl-a (Copernicus 자격증명 미설정)")
    else:
        def _sat():
            import fetch_satellite_chl
            fetch_satellite_chl.main()
        step("위성 chl-a", ARTIFACT / "satellite_chl_daily.parquet", _sat, force)

    # 5) 학습 (라벨 + 특성 + 모델)
    print("\n[5/6] 모델 학습 (시간순 split + walk-forward CV)")
    def _train():
        import train_v2
        train_v2.main()
    step("v2 학습", ARTIFACT / "risk_model_v2.joblib", _train, force=True)

    # 6) 완료 안내
    print("\n[6/6] 완료")
    print("  · 다음 명령으로 서버 실행:")
    print("      uvicorn main:app --host 127.0.0.1 --port 8000")
    print("  · 브라우저: http://127.0.0.1:8000")


if __name__ == "__main__":
    force = "--force" in sys.argv
    main(force=force)
