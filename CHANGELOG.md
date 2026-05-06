# Changelog

본 프로젝트는 [Semantic Versioning](https://semver.org/lang/ko/) (`MAJOR.MINOR.PATCH`)을 따른다.

- **MAJOR**: 호환되지 않는 API/스키마/모델 변경
- **MINOR**: 하위 호환되는 기능 추가 (UI 섹션 추가, 신규 엔드포인트 등)
- **PATCH**: 하위 호환되는 버그·표시 수정

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
