#!/usr/bin/env bash
# 적조예측 플랫폼 원클릭 실행 (macOS / Linux)
set -e
cd "$(dirname "$0")/backend"

if [ ! -d ".venv" ]; then
  echo "[setup] 가상환경 생성"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "[setup] 의존성 설치"
python -m pip install --upgrade pip > /dev/null
pip install -q -r requirements.txt

if [ ! -f "artifacts/risk_model_v2.joblib" ]; then
  echo "[setup] 데이터/모델 미존재 → setup_data.py 실행 (15~30분)"
  python setup_data.py
fi

echo "[serve] http://127.0.0.1:8000"
exec uvicorn main:app --host 127.0.0.1 --port 8000
