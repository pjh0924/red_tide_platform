"""환경 변수 / API 키 로딩."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(__file__).parent / ".env"
load_dotenv(ENV_PATH)

DATA_GO_KR_KEY = os.getenv("DATA_GO_KR_KEY", "").strip()
KMA_API_KEY = os.getenv("KMA_API_KEY", "").strip() or DATA_GO_KR_KEY
COPERNICUS_USERNAME = os.getenv("COPERNICUS_USERNAME", "").strip()
COPERNICUS_PASSWORD = os.getenv("COPERNICUS_PASSWORD", "").strip()


def require(key_name: str) -> str:
    val = os.getenv(key_name, "").strip()
    if not val:
        raise RuntimeError(
            f"환경변수 {key_name} 가 비어있습니다. backend/.env 파일을 확인하세요."
        )
    return val
