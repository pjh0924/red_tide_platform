"""공공데이터포털(data.go.kr) 공통 호출 헬퍼."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests


class APIError(RuntimeError):
    pass


@dataclass
class GoKrClient:
    """data.go.kr 공통 클라이언트.

    - serviceKey 자동 첨부
    - JSON 응답 우선, XML fallback
    - 429/5xx 재시도
    """
    service_key: str
    timeout: float = 15.0
    max_retries: int = 3
    backoff: float = 1.5

    def get(self, url: str, params: dict[str, Any] | None = None,
            response_type: str = "JSON") -> dict:
        params = dict(params or {})
        # data.go.kr 는 디코딩된 키와 인코딩된 키 둘 다 받지만, requests 가
        # 자동 인코딩하므로 디코딩된 원본 키를 그대로 넘긴다.
        params["serviceKey"] = self.service_key
        params.setdefault("dataType", response_type)
        params.setdefault("type", response_type.lower())  # 일부 서비스는 type 사용

        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                r = requests.get(url, params=params, timeout=self.timeout)
                if r.status_code in (429, 500, 502, 503, 504):
                    raise APIError(f"HTTP {r.status_code}")
                r.raise_for_status()
                # 일부 응답은 200 OK 라도 XML 에러를 담아옴
                text = r.text
                if "<OpenAPI_ServiceResponse>" in text or "<errMsg>" in text:
                    raise APIError(f"data.go.kr error response: {text[:300]}")
                if response_type.upper() == "JSON":
                    return r.json()
                return {"_raw_xml": text}
            except (requests.RequestException, APIError, ValueError) as e:
                last_err = e
                if attempt < self.max_retries - 1:
                    time.sleep(self.backoff ** attempt)
        raise APIError(f"요청 실패 ({self.max_retries}회 재시도): {last_err}")
