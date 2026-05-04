# 적조예측 플랫폼 원클릭 실행 스크립트 (Windows PowerShell)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\backend

if (-not (Test-Path .\.venv)) {
    Write-Host "[setup] 가상환경 생성"
    python -m venv .venv
}
. .\.venv\Scripts\Activate.ps1

Write-Host "[setup] 의존성 설치"
python -m pip install --upgrade pip *> $null
pip install -r requirements.txt

if (-not (Test-Path .\artifacts\forecaster.joblib)) {
    Write-Host "[train] 모델 학습 (최초 1회, 1~2분 소요)"
    python train.py
}

Write-Host "[serve] http://127.0.0.1:8000 에서 실행"
uvicorn main:app --host 127.0.0.1 --port 8000
