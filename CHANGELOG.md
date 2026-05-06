# Changelog

본 프로젝트는 [Semantic Versioning](https://semver.org/lang/ko/) (`MAJOR.MINOR.PATCH`)을 따른다.

- **MAJOR**: 호환되지 않는 API/스키마/모델 변경
- **MINOR**: 하위 호환되는 기능 추가 (UI 섹션 추가, 신규 엔드포인트 등)
- **PATCH**: 하위 호환되는 버그·표시 수정

## [1.2.1] - 2026-05-06

지도 위 PoC 어장 점선 박스의 실제 범위를 km 단위로 가시화. 미팅·시연 시 격자 스케일 즉시 파악 가능.

### 추가 (프론트엔드)
- Leaflet 기본 스케일 바(좌하단) — 줌 레벨에 맞춘 km 척도 자동 표시.
- PoC 어장 bbox 변 중앙에 가로/세로 km 라벨(`↔ 5.0 km`, `↕ 5.0 km`) 오버레이.
- bbox 툴팁에 `범위 W × H km · 격자 N×M (1×1km)` 추가 표기.

## [1.2.0] - 2026-05-06

어군 실시간 모니터링 인프라 1차 골격. 본 사업의 중심축이 적조에서 어군 사전 탐지로 재설정됨에 따라, 드론·AIS·1km 격자 라벨링까지 데이터 파이프라인 전체를 추가했다. 실제 드론 업체·AIS 라이선스 확보 전에도 파일 드롭 인제스트와 데모 생성기로 end-to-end 검증 가능.

### 추가 (백엔드)
- `backend/fetchers/drone.py` — 수상드론 어군 탐지 결과 수집. `DroneDetection` 스키마 + `artifacts/drone/incoming/` 파일 드롭 인제스트 + `load_detections()`/`list_missions()` 조회. 실시간 API 어댑터는 PoC 후 채울 스텁.
- `backend/fetchers/ais.py` — AIS 어선 위치 데이터. `AISFix` 스키마 + 파일 드롭 + SOG 1~5kn 어업 활동 휴리스틱(`estimate_fishing_activity`) + 선박별 체류시간 요약. 실시간 소스 후보 4곳 문서화(해수부 어선위치정보·MarineTraffic·AISHub·AISStream).
- `backend/data_pipeline/fish_grid.py` — 1×1km 격자 × 시간 단위 어군 밀도 라벨 빌더. `Zone` 정의 3곳(통영 욕지/남해 미조/거제 매물). 드론 + AIS 신호를 z-score 후 시그모이드로 합성한 `fish_density_score`(0~1).
- `backend/generate_drone_ais_demo.py` — 7일치 드론 28미션·AIS 12척 합성 데이터 생성기.
- FastAPI 엔드포인트: `/api/fish/zones`, `/api/drone/{ingest,missions,detections}`, `/api/ais/{ingest,fixes,dwell}`, `/api/fish/{density,monitoring/summary}`.

### 추가 (프론트엔드)
- 새 패널 **🚁 어군 실시간 모니터링**: PoC 어장 셀렉터 · 시간 범위 셀렉터(1h~7d) · KPI 4종(활성 미션·드론 탐지·어업 어선·핫스팟 점수) · 어종 분포 미니 바차트 · Top 5 핫스팟 격자 리스트.
- 지도 오버레이: 선택 어장 bbox 사각형(점선) + 핫스팟 격자 빨간 원(밀도 점수 비례 크기). 핫스팟 클릭 시 지도가 해당 좌표로 이동.
- 어종 코드 → 한국어 매핑(고등어/정어리/멸치/전갱이/삼치/가자미/조피볼락/미식별).
- 5분 자동 갱신.

### 변경
- `.gitignore`에 `backend/artifacts/drone/`, `ais/`, `fish_density_*.parquet` 추가 (운영 데이터·데모 산출물 비커밋).

## [1.1.0] - 2026-05-06

### 변경
- 차트의 NIFS 적조 발생 이력 표시를 점(scatter)에서 **반투명 빨간색 세로 띠**(annotation box)로 변경. 발생일이 차트 전 영역을 가로질러 보이도록 가시성 개선.
- 범례 텍스트 갱신: "NIFS 적조 발생 이력 (반투명 띠)".

### 추가
- `chartjs-plugin-annotation@3.0.1` CDN 의존성.

### 제거
- 더 이상 사용하지 않는 hidden y4 축.

## [1.0.0] - 2026-05-06

### 추가
- 좌측 사이드바에 **지표 설명** 섹션: 수온(SST)·염분·클로로필-a·DIN/DIP/DO/pH·기상 입력의 의미와 적조와의 연관성.
- 좌측 사이드바에 **AI 모델** 섹션: HistGradientBoostingClassifier × 3 horizons, 학습 데이터 구성, chronological holdout + walk-forward CV 5폴드, AUROC 성능.
- 차트 범례·Y축·dataset label "SST" → "수온(SST)" 한국어 병기.

### 수정
- 메인 영역이 뷰포트에 강제 고정되어 하단 차트가 잘리던 문제 수정. `.app`/`main`을 `min-height` 기반으로 변경하고 패널 `min-height` 부여하여 페이지 스크롤로 모든 패널 열람 가능.

## [0.x] - 시작 (태그 없음)

태그가 부여되기 이전의 초기 개발 이력. 주요 마일스톤:
- E2E 검증 스크립트 추가 (`db5d15b`)
- 어종 출현 확률 모듈(heuristic, 7종) 추가 (`d00a7ad`)
- 실시간 환경 panel + 남해안 wide view + KOEM raw observations (`9ff2ba4`)
- 적조예측 플랫폼 v2 초기 커밋 (`fae32a6`)
