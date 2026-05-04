# 🌊 적조예측 플랫폼 (Red Tide Forecast)

경남 연안(서부·중부·동부) 3개 광역해역에 대한 **적조 발생 확률 예측 (1·3·7일)** 풀스택 시스템.
실데이터 기반: **해양환경공단(KOEM) + 기상청(KMA) + 국립수산과학원(NIFS) + Copernicus 위성**.

---

## ⚡ 빠른 시작 (3 단계)

### 1. clone
```bash
git clone https://github.com/pjh0924/red_tide_platform.git
cd red_tide_platform
```

### 2. API 키 입력
```bash
cp backend/.env.example backend/.env
# 편집기로 backend/.env 열어서 본인 키 입력
```
| 키 | 용도 | 어디서 |
|---|---|---|
| `DATA_GO_KR_KEY` | KOEM/NIFS/KMA 통합 (필수) | https://www.data.go.kr/ |
| `KMA_API_KEY` | (선택, 비워두면 위 키 재사용) | 동일 |
| `COPERNICUS_USERNAME/PASSWORD` | 위성 chl-a (선택) | https://data.marine.copernicus.eu/register |

### 3. 실행
**Windows (PowerShell)**
```powershell
.\run.ps1
```
**macOS / Linux**
```bash
./run.sh
```

브라우저 → http://127.0.0.1:8000

> 처음 실행 시 학습된 모델 ([artifacts/risk_model_v2.joblib](backend/artifacts/risk_model_v2.joblib)) 이
> 이미 포함되어 있어 데이터 다운로드 단계를 건너뛰고 바로 서버가 시작됩니다.
> 최신 데이터로 다시 학습하려면 `python backend/setup_data.py --force` 실행.

---

## 📦 패키지 구성

```
red_tide_platform/
├── backend/
│   ├── fetchers/                 외부 API 호출
│   │   ├── kma_asos.py             기상청 ASOS (시간/일자료)
│   │   ├── koem.py                 해양환경공단 측정망 V2
│   │   └── nifs_redtide.py         국립수산과학원 적조속보 크롤러
│   ├── data_pipeline/            라벨/특성 빌드
│   │   ├── regions.py              경남 3 region 정의 + 매핑
│   │   ├── labels.py               NIFS → (region, date) 라벨
│   │   └── features.py             KOEM + ASOS as-of merge → 일별 features
│   ├── model_v2.py               HistGradientBoosting 다중호라이즌 분류기
│   ├── train_v2.py               시간순 holdout + walk-forward CV 학습
│   ├── main.py                   FastAPI v2
│   ├── stations.py               경남 8개 가상 관측소
│   ├── setup_data.py             ★ 원클릭 데이터 수집 + 학습
│   ├── fetch_*.py                개별 데이터 fetcher
│   ├── crawl_nifs_full.py        NIFS 전수 크롤
│   ├── requirements.txt
│   └── artifacts/                데이터 + 학습된 모델 (git 포함)
├── frontend/index.html           Leaflet + Chart.js
├── run.sh / run.ps1              원클릭 실행
├── .env.example                  키 입력 템플릿
└── README.md
```

---

## 🧠 모델 개요

| 항목 | 값 |
|---|---|
| **예측 대상** | 경남서부 / 경남중부 / 경남동부 |
| **시간 단위** | 일별 |
| **출력** | 향후 1·3·7일 적조 발생 확률 (HistGradientBoostingClassifier × 3 horizons) |
| **입력** | KOEM 7종 (수온/염분/pH/DO/DIN/DIP/chl-a) + ASOS 4종 (일사/풍속/기온/강수) + rolling(7,30) + 계절 |
| **평가** | Chronological holdout (2023-01-01 cut) + Walk-forward CV (5 folds) |

**최신 성능 (KOEM + ASOS, 위성 미포함)**:

| Horizon | Holdout AUROC | Walk-forward CV (mean ± std) |
|---|---|---|
| +1d | 0.85 | 0.78 ± 0.06 |
| +3d | 0.85 | 0.74 ± 0.06 |
| +7d | 0.87 | 0.74 ± 0.06 |

---

## 🔌 REST API

| 경로 | 응답 |
|---|---|
| `GET /api/regions` | 3개 광역해역 + 현재 위험도 |
| `GET /api/regions/{r}/forecast` | 향후 1·3·7일 발생 확률 |
| `GET /api/regions/{r}/observations?days=180` | KOEM 일별 관측치 |
| `GET /api/regions/{r}/history?days=730` | NIFS 적조 발생 이력 |
| `GET /api/stations` | 8개 가상 관측소 + 소속 region 위험도 |
| `GET /api/summary` | 위험도별 region 수 |

---

## 🔄 데이터 갱신

매일 한 번 데이터 갱신 + 재학습이 필요하면:

```bash
cd backend
python setup_data.py --force
```

또는 cron 으로:
```cron
0 6 * * * cd /path/to/red_tide_platform/backend && .venv/bin/python setup_data.py --force
```

---

## ⚠️ 알려진 한계

1. **KOEM이 분기/월 측정** → 일별 features 는 직전 측정값을 forward-fill (tolerance 365일)
2. **NIFS 라벨은 주의보 발령 해역만 등재** → 모든 미게재일을 음성으로 가정 (under-reporting bias)
3. **위성 chl-a 보류** — region별 평균 차이가 train/test shift 에 너무 민감 (raw 통합 시 holdout AUROC 0.10 하락). 데이터는 [artifacts/satellite_chl_daily.parquet](backend/artifacts/satellite_chl_daily.parquet) 에 보관, 향후 region-aware calibration 후 재통합 가능
4. **KHOA 부이/조위수온** — endpoint HTTP 500 (활성화 대기), fetcher 는 미구현

---

## 📜 데이터 출처 / 라이선스

- **KOEM**: 해양환경공단 해양환경측정망 (data.go.kr)
- **KMA**: 기상청 ASOS 일자료 (data.go.kr)
- **NIFS**: 국립수산과학원 적조정보시스템 (https://www.nifs.go.kr/board/actionRedtideInfoList.do)
- **Copernicus Marine**: Copernicus-GlobColour L4 daily (CC-BY 4.0)

본 저장소의 `artifacts/` 데이터는 위 공공데이터의 가공물입니다. 원 데이터의 라이선스 조건에 따릅니다.

## ⚖️ Disclaimer

본 시스템은 **연구·교육용 데모**이며 어업·재해 의사결정에 직접 사용하지 마십시오.
공식 적조 경보는 [국립수산과학원](https://www.nifs.go.kr/board/actionRedtideInfoList.do) 발표를 따르세요.
