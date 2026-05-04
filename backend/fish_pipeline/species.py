"""한국 남해 주요 어종 정의 + 알려진 환경 최적조건.

각 어종의 최적 환경 (수온/염분) 과 회유/계절성을 가우시안 + 월별 가중치로 표현.
출처: 국립수산과학원 자원생태 연구보고서, FishBase, 한국해양생태보고서 종합.
숫자는 문헌 기반 1차 근사 — 향후 KOSIS 어획 라벨로 ML 학습 시 자동 보정 예정.
"""
from __future__ import annotations

SPECIES = [
    {
        "id": "anchovy", "ko": "멸치", "sci": "Engraulis japonicus",
        "habitat": "표층",
        "sst_center": 20.0, "sst_sigma": 4.0,
        "sal_center": 32.0, "sal_sigma": 1.5,
        # 월별 출현 가중치 (1~12월). 봄·가을 회유 + 여름 멸치 조업 고려
        "month_weight": [0.3, 0.4, 0.7, 1.0, 1.1, 1.0, 0.9, 0.9, 1.0, 1.1, 0.7, 0.4],
        "color": "#4ea1ff",
    },
    {
        "id": "mackerel", "ko": "고등어", "sci": "Scomber japonicus",
        "habitat": "표층/중층",
        "sst_center": 18.0, "sst_sigma": 4.5,
        "sal_center": 33.0, "sal_sigma": 1.2,
        "month_weight": [0.4, 0.4, 0.6, 0.9, 1.1, 1.0, 0.7, 0.6, 0.9, 1.2, 1.1, 0.7],
        "color": "#2ecc71",
    },
    {
        "id": "hairtail", "ko": "갈치", "sci": "Trichiurus lepturus",
        "habitat": "중층",
        "sst_center": 21.0, "sst_sigma": 4.5,
        "sal_center": 33.5, "sal_sigma": 1.3,
        "month_weight": [0.2, 0.2, 0.4, 0.6, 0.8, 1.0, 1.1, 1.1, 1.2, 1.2, 0.9, 0.5],
        "color": "#f1c40f",
    },
    {
        "id": "spanish_mackerel", "ko": "삼치", "sci": "Scomberomorus niphonius",
        "habitat": "표층/중층",
        "sst_center": 17.0, "sst_sigma": 4.0,
        "sal_center": 33.0, "sal_sigma": 1.2,
        "month_weight": [0.3, 0.4, 0.7, 1.0, 1.1, 0.8, 0.5, 0.5, 0.9, 1.2, 1.1, 0.6],
        "color": "#e67e22",
    },
    {
        "id": "horse_mackerel", "ko": "전갱이", "sci": "Trachurus japonicus",
        "habitat": "표층/중층",
        "sst_center": 19.0, "sst_sigma": 4.5,
        "sal_center": 33.0, "sal_sigma": 1.5,
        "month_weight": [0.4, 0.4, 0.6, 0.9, 1.0, 1.0, 0.9, 0.9, 1.0, 1.1, 0.9, 0.5],
        "color": "#9b59b6",
    },
    {
        "id": "red_seabream", "ko": "참돔", "sci": "Pagrus major",
        "habitat": "저층(연안 정착성)",
        "sst_center": 17.0, "sst_sigma": 3.5,
        "sal_center": 33.0, "sal_sigma": 1.2,
        "month_weight": [0.6, 0.7, 0.9, 1.1, 1.2, 1.0, 0.8, 0.8, 1.0, 1.1, 0.9, 0.7],
        "color": "#e74c3c",
    },
    {
        "id": "rockfish", "ko": "우럭", "sci": "Sebastes schlegelii",
        "habitat": "저층(암반 정착성)",
        "sst_center": 13.0, "sst_sigma": 4.0,
        "sal_center": 32.5, "sal_sigma": 1.3,
        "month_weight": [1.0, 1.1, 1.2, 1.1, 1.0, 0.7, 0.5, 0.5, 0.7, 0.9, 1.0, 1.0],
        "color": "#16a085",
    },
]


def get_species(species_id: str) -> dict | None:
    return next((s for s in SPECIES if s["id"] == species_id), None)


def all_species_ids() -> list[str]:
    return [s["id"] for s in SPECIES]
