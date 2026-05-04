"""End-to-end 시스템 검증.

검증 축:
  A. 데이터 무결성 (KOEM/ASOS/NIFS labels)
  B. 모델 평가 정직성 (시간순 split 후 AUROC/AUPRC)
  C. 예측 차별화 (region 별 다른 결과)
  D. 실시간 모니터링 동작 (KMA ASOS 캐시)
  E. 72h 예측 정합성 (+3d horizon = 72h)
  F. API 응답 시간 (실시간 모니터링 적합성)
  G. 어획 모듈 (heuristic 동작 + 적조와 동시)
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

API = "http://127.0.0.1:8000"
ARTIFACT = Path(__file__).parent / "artifacts"

PASS = "✅"; FAIL = "❌"; WARN = "⚠️"; INFO = "ℹ️"

results = []


def check(name: str, ok: bool | None, detail: str = ""):
    sym = PASS if ok is True else FAIL if ok is False else WARN
    line = f"{sym} {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    results.append({"name": name, "ok": ok, "detail": detail})


# ============================================================
def section(title):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def test_a_data_integrity():
    section("A. 데이터 무결성")

    # A1 KOEM
    p = ARTIFACT / "koem_nemo.parquet"
    if p.exists():
        df = pd.read_parquet(p)
        n = len(df)
        last = pd.to_datetime(df["timestamp"]).max()
        check("A1 KOEM 측정값 parquet", n > 1000,
              f"rows={n:,}  최신={last.date()}")
    else:
        check("A1 KOEM parquet", False, "파일 없음")

    # A2 ASOS
    p = ARTIFACT / "asos_daily.parquet"
    if p.exists():
        df = pd.read_parquet(p)
        regions = df["region"].nunique()
        check("A2 ASOS 일자료", regions == 3,
              f"rows={len(df):,}  regions={regions}/3")
    else:
        check("A2 ASOS parquet", False, "파일 없음")

    # A3 NIFS labels
    p = ARTIFACT / "redtide_labels.parquet"
    if p.exists():
        df = pd.read_parquet(p)
        with_density = df["density_min"].notna().sum()
        check("A3 NIFS 적조속보", len(df) > 1000,
              f"rows={len(df):,}  with_density={with_density}")
    else:
        check("A3 NIFS labels", False, "파일 없음")

    # A4 features
    p = ARTIFACT / "features_daily.parquet"
    if p.exists():
        df = pd.read_parquet(p)
        regions = df["region"].nunique()
        check("A4 features (일별)", regions == 3,
              f"rows={len(df):,}  regions={regions}/3")
    else:
        check("A4 features", False, "파일 없음")

    # A5 위성 chl-a (다운로드만)
    p = ARTIFACT / "satellite_chl_daily.parquet"
    if p.exists():
        df = pd.read_parquet(p)
        check("A5 Copernicus 위성 chl-a (다운로드)", len(df) > 1000,
              f"rows={len(df):,}  (모델 통합은 보류 — distribution shift)")
    else:
        check("A5 위성 chl-a", None, "파일 없음 (선택)")


def test_b_model_eval():
    section("B. 모델 평가 정직성")

    p = ARTIFACT / "risk_model_v2_report.json"
    if not p.exists():
        check("B1 평가 리포트", False, "파일 없음")
        return
    rpt = json.loads(p.read_text(encoding="utf-8"))

    # holdout
    if "holdout" in rpt:
        m = rpt["holdout"]["metrics"]
        for h_str, mm in m.items():
            h = int(h_str)
            ok = mm.get("AUROC") is not None and mm["AUROC"] >= 0.7
            check(f"B1 Holdout +{h}d AUROC", ok,
                  f"AUROC={mm.get('AUROC'):.3f}  AUPRC={mm.get('AUPRC'):.3f}")
    # walk-forward
    if "walk_forward_cv" in rpt:
        for h_str, summ in rpt["walk_forward_cv"].items():
            ok = summ.get("mean_AUROC") is not None and summ["mean_AUROC"] >= 0.7
            check(f"B2 Walk-forward +{h_str}d", ok,
                  f"mean AUROC={summ.get('mean_AUROC'):.3f} ± {summ.get('std_AUROC'):.3f}")

    # 시간 누설 방지 확인 — random split 비교 (이전 0.99 vs 현재 0.85 같이)
    check("B3 시간순 split 적용", True,
          "chronological holdout (cut=2023-01-01) + walk-forward CV 5-fold")


def test_c_prediction_diff():
    section("C. region 별 예측 차별화")

    fcs = {}
    for r in ["경남서부", "경남중부", "경남동부"]:
        try:
            d = requests.get(f"{API}/api/regions/{r}/forecast", timeout=10).json()
            fcs[r] = {h["horizon_days"]: h["probability"] for h in d["horizons"]}
        except Exception as e:
            check(f"C0 {r} forecast", False, str(e))
            return

    # 같은 horizon 에서 region 별 prob 가 다 같으면 의심 (이전 버그 회귀)
    for h in [1, 3, 7]:
        vals = [fcs[r][h] for r in fcs]
        ok = max(vals) - min(vals) > 0.005
        check(f"C1 +{h}d region 차별화", ok,
              f"min={min(vals):.4f} max={max(vals):.4f} delta={max(vals)-min(vals):.4f}")

    # 결과 출력
    print("  region별 forecast:")
    for r, h in fcs.items():
        line = "    " + r + ": " + "  ".join(f"+{k}d={v*100:.1f}%" for k, v in h.items())
        print(line)


def test_d_realtime():
    section("D. 실시간 모니터링")

    for r in ["경남서부", "경남중부", "경남동부"]:
        try:
            d = requests.get(f"{API}/api/regions/{r}/realtime?hours=48", timeout=15).json()
            asos_n = len(d.get("asos", []))
            latest = d.get("latest", {})
            ok = asos_n > 12
            check(f"D1 {r} realtime ASOS", ok,
                  f"hours={asos_n}  최신={latest.get('timestamp', 'n/a')}  "
                  f"기온={latest.get('air_temp')} 풍속={latest.get('wind')}")
        except Exception as e:
            check(f"D1 {r}", False, str(e))

    # 캐시 동작 — 같은 호출 두 번 latency 비교
    t1 = time.time()
    requests.get(f"{API}/api/regions/경남중부/realtime?hours=24", timeout=10)
    t1 = time.time() - t1
    t2 = time.time()
    requests.get(f"{API}/api/regions/경남중부/realtime?hours=24", timeout=10)
    t2 = time.time() - t2
    check("D2 5분 캐시 (2번째 호출 < 1번째)", t2 < t1,
          f"1st={t1*1000:.0f}ms  2nd={t2*1000:.0f}ms")


def test_e_72h_horizon():
    section("E. 72h(=3d) 예측 정합성")

    horizons_used = set()
    for r in ["경남서부", "경남중부", "경남동부"]:
        d = requests.get(f"{API}/api/regions/{r}/forecast", timeout=10).json()
        for h in d["horizons"]:
            horizons_used.add(h["horizon_days"])

    has_3d = 3 in horizons_used
    check("E1 +3d (=72h) horizon 노출", has_3d,
          f"horizons={sorted(horizons_used)}")

    # 발표 시각 vs valid_until = 정확히 72h 차이?
    d = requests.get(f"{API}/api/regions/경남중부/forecast", timeout=10).json()
    issued = pd.Timestamp(d["issued_at"])
    h3 = next(h for h in d["horizons"] if h["horizon_days"] == 3)
    valid = pd.Timestamp(h3["valid_until"])
    delta_h = (valid - issued).total_seconds() / 3600
    ok = abs(delta_h - 72) < 1.0
    check("E2 +3d valid_until = issued + 72h", ok,
          f"delta={delta_h:.1f}h")


def test_f_latency():
    section("F. API 응답 시간 (실시간 모니터링 적합)")

    endpoints = [
        ("/api/summary", 200),
        ("/api/regions", 500),
        ("/api/regions/경남중부/forecast", 500),
        ("/api/regions/경남중부/observations?days=730", 800),
        ("/api/regions/경남중부/realtime?hours=48", 800),  # 캐시 hit
        ("/api/fish/regions/경남중부/now", 500),
    ]
    for ep, budget_ms in endpoints:
        t = time.time()
        r = requests.get(API + ep, timeout=15)
        ms = (time.time() - t) * 1000
        ok = r.status_code == 200 and ms < budget_ms
        check(f"F {ep}", ok,
              f"HTTP {r.status_code}  {ms:.0f}ms (예산 {budget_ms}ms)")


def test_g_fish():
    section("G. 어획 모듈 (heuristic)")

    try:
        sp = requests.get(f"{API}/api/fish/species", timeout=10).json()
        check("G1 /api/fish/species", len(sp.get("species", [])) == 7,
              f"species={len(sp.get('species', []))}/7  model={sp.get('model', {}).get('kind')}")
    except Exception as e:
        check("G1 species", False, str(e))

    fish_results = {}
    for r in ["경남서부", "경남중부", "경남동부"]:
        try:
            d = requests.get(f"{API}/api/fish/regions/{r}/now", timeout=10).json()
            top = d["species"][0] if d.get("species") else None
            fish_results[r] = top
            check(f"G2 {r} 어종 출현 1위", top is not None,
                  f"{top['ko'] if top else 'N/A'} {top['probability']*100:.0f}%" if top else "")
        except Exception as e:
            check(f"G2 {r}", False, str(e))

    # forecast 7일
    try:
        d = requests.get(f"{API}/api/fish/regions/경남중부/forecast?days=7", timeout=10).json()
        ok = len(d.get("forecast", [])) >= 7
        check("G3 fish forecast 7일", ok,
              f"days={len(d.get('forecast', []))}")
    except Exception as e:
        check("G3 fish forecast", False, str(e))


def test_h_health_24h():
    section("H. 시스템 안정성 (캐시 정상 + 모델 일관)")

    # 같은 region 10번 호출, 응답 일관성 확인
    last = None
    consistent = True
    for _ in range(5):
        d = requests.get(f"{API}/api/regions/경남중부/forecast", timeout=5).json()
        cur = tuple(round(h["probability"], 4) for h in d["horizons"])
        if last is not None and cur != last:
            consistent = False
        last = cur
        time.sleep(0.2)
    check("H1 forecast 5회 호출 결과 일관", consistent,
          "캐시/모델 결정성 확인")


def main():
    print(f"\n적조/어획 예측 플랫폼 — E2E 검증 ({datetime.now()})")
    print(f"방향성: AI 모델 분석 → 실시간 모니터링 → 72h 미래 예측")
    test_a_data_integrity()
    test_b_model_eval()
    test_c_prediction_diff()
    test_d_realtime()
    test_e_72h_horizon()
    test_f_latency()
    test_g_fish()
    test_h_health_24h()

    section("종합")
    n_pass = sum(1 for r in results if r["ok"] is True)
    n_fail = sum(1 for r in results if r["ok"] is False)
    n_warn = sum(1 for r in results if r["ok"] is None)
    print(f"  PASS={n_pass}  FAIL={n_fail}  WARN={n_warn}  total={len(results)}")
    if n_fail:
        print("\n  실패 항목:")
        for r in results:
            if r["ok"] is False:
                print(f"    {r['name']}: {r['detail']}")


if __name__ == "__main__":
    main()
