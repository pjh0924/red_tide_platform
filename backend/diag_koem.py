"""KOEM 엔드포인트 진단: raw 응답을 그대로 출력해서 정확한 경로/스키마 파악."""
from __future__ import annotations

import requests

import config

KEY = config.DATA_GO_KR_KEY

# 시도해볼 후보 경로 (data.go.kr B553931 KOEM 패턴 변형)
CANDIDATES = [
    # 검색에서 본 URL
    "http://apis.data.go.kr/B553931/service/OceansNseaInfoService1/getOceansNseaInfo1",
    "http://apis.data.go.kr/B553931/service/OceansWemoReInfoService1/getOceansWemoReInfo1",
    "http://apis.data.go.kr/B553931/service/OceansNemoService1/getOceansNemo1",
    "http://apis.data.go.kr/B553931/service/OceansNemoCtdService1/getOceansNemoCtd1",
    # 변형: Service1 → ReService1 / 단수형 / 다른 메서드명
    "http://apis.data.go.kr/B553931/service/OceansNemoReService1/getOceansNemoRe1",
    "http://apis.data.go.kr/B553931/service/OceansNemoCtdReService1/getOceansNemoCtdRe1",
    # base 만 존재하는지
    "http://apis.data.go.kr/B553931/service/OceansNemoService1",
]


def probe(url: str):
    print("\n" + "-" * 80)
    print(f"GET {url}")
    try:
        r = requests.get(url, params={"serviceKey": KEY, "pageNo": 1, "numOfRows": 1,
                                       "resultType": "xml"}, timeout=10)
        print(f"HTTP {r.status_code}  Content-Type: {r.headers.get('content-type','')}")
        print(f"length: {len(r.text)} chars")
        print("body[:500]:")
        print(r.text[:500])
    except Exception as e:
        print(f"EXC: {e}")


for url in CANDIDATES:
    probe(url)
