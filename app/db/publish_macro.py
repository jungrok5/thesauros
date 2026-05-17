"""Publish macro state to Supabase `macro_state` (singleton row, id=1).

Uses the existing app.macro module:
  - `app.macro.state.market_regime()` for the headline regime score
  - `app.macro.state.all_states()` for per-indicator values + verdict
  - `app.macro.state.categorized()` for the category breakdown

Adds a book-specific 5-axis dial computed locally (liquidity/rate/cycle/
price/fear) so the dashboard can render `통화·금리·경기·물가·공포`
as colored dots without further round-trips.

Usage:
    python -m app.db.publish_macro
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.db import get_conn               # noqa: E402
from app.macro.state import (              # noqa: E402
    all_states, categorized, market_regime,
)


# ---------- 5-axis dial (book-faithful summary) ------------------------------

DIAL_AXIS = ("liquidity", "rate", "cycle", "price", "fear")


def _score_from_state(s: str) -> int:
    return {"BULL": 5, "NEUTRAL": 3, "CAUTION": 2, "BEAR": 1}.get(s, 3)


def _axis_score(indicators: list, keys: list) -> int:
    vals = [_score_from_state(i["state"]) for i in indicators if i["key"] in keys]
    if not vals:
        return 3
    return int(round(sum(vals) / len(vals)))


# Map book chapter macro indicators → 5 dial axes.
DIAL_KEY_MAP = {
    "liquidity": ["m2_money_supply", "fed_balance_sheet",
                  "credit_spread_ig", "credit_spread_hy"],
    "rate":      ["fed_funds_rate", "yield_curve_10y2y",
                  "real_rate_10y", "tips_breakeven_10y"],
    "cycle":     ["ism_pmi", "ism_services", "industrial_production",
                  "unit_labor_cost", "unemployment", "weekly_leading_index"],
    "price":     ["cpi_yoy", "core_pce_yoy", "ppi_yoy"],
    "fear":      ["vix", "credit_spread_hy", "ted_spread", "dxy",
                  "gold_yoy"],
}


def compute_dial(states: list) -> Dict[str, int]:
    return {axis: _axis_score(states, DIAL_KEY_MAP[axis]) for axis in DIAL_AXIS}


def dial_total_guidance(scores: Dict[str, int]) -> str:
    total = sum(scores.values())   # 5..25
    if total >= 20: return "🟢 매수 강력 우호 — 책 17종 기법 적극 활용"
    if total >= 15: return "🟢 매수 우호 — 양호 업종 + 강한 신호 종목 우선"
    if total >= 10: return "🟡 중립 — 신호 명확한 종목만 신중 매수"
    if total >= 5:  return "🟠 신중 — 인덱스 인버스 비중 검토"
    return "🔴 방어 — 책: 인버스 / 현금 보유도 일종의 투자 (p394)"


# ---------- MV=PQ signal (피셔 방정식) --------------------------------------

def mv_pq_signal(states: list) -> str:
    by_key = {s["key"]: s for s in states}
    m2_yoy = (by_key.get("m2_money_supply") or {}).get("yoy_pct")
    kospi_yoy = (by_key.get("kospi") or {}).get("yoy_pct")
    if m2_yoy is None or kospi_yoy is None:
        return "🟡 데이터 부족"
    if m2_yoy > 5 and kospi_yoy < -20:
        return "🚨 위기=기회 매수 시그널 — 유동성↑ + 시장 저점"
    if m2_yoy > 6 and kospi_yoy > 30:
        return "⚠️ 버블 경고 — 유동성 vs 자산 가격 과열"
    if m2_yoy > 4:
        return "🟢 자산 가격 상승 압력 (M↑) — 주식·부동산 우호"
    if m2_yoy < 1:
        return "🟠 디플레이션 압력 — 채권·현금 비중 검토"
    return "🟡 균형 — 정상 환경"


# ---------- entrypoint -------------------------------------------------------

def build_payload() -> Dict[str, Any]:
    states = [s.to_dict() for s in all_states()]
    regime = market_regime()
    cats = categorized()
    dial = compute_dial(states)

    # indices breakdown (per-major-index regime — populate later when added
    # to macro/indicators.py). Placeholder:
    indices = {}
    for key in ("sp500", "nasdaq", "dow", "kospi", "kosdaq", "nikkei", "shanghai"):
        ind = next((s for s in states if s["key"] == key), None)
        if ind:
            indices[key] = ind["state"]

    return {
        "global_status": "bull" if regime["score"] > 0.2
                          else ("bear" if regime["score"] < -0.2 else "mixed"),
        "kr_status": indices.get("kospi", "unknown"),
        "indices": indices,
        "macro_indicators": {s["key"]: s for s in states},
        "mv_pq_signal": mv_pq_signal(states),
        "dial_scores": dial,
        "one_line_guidance": dial_total_guidance(dial),
        "_regime": regime,
        "_categorized": cats,
    }


def publish() -> int:
    payload = build_payload()
    macro_json = json.dumps(payload["macro_indicators"], ensure_ascii=False, default=str)
    indices_json = json.dumps(payload["indices"], ensure_ascii=False)
    dial_json = json.dumps(payload["dial_scores"])
    regime_json = json.dumps(payload["_regime"], ensure_ascii=False, default=str)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO macro_state
                  (id, global_status, kr_status, indices, macro_indicators,
                   mv_pq_signal, dial_scores, one_line_guidance, regime,
                   updated_at)
                VALUES (1, %s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb, %s,
                        %s::jsonb, now())
                ON CONFLICT (id) DO UPDATE SET
                   global_status = EXCLUDED.global_status,
                   kr_status = EXCLUDED.kr_status,
                   indices = EXCLUDED.indices,
                   macro_indicators = EXCLUDED.macro_indicators,
                   mv_pq_signal = EXCLUDED.mv_pq_signal,
                   dial_scores = EXCLUDED.dial_scores,
                   one_line_guidance = EXCLUDED.one_line_guidance,
                   regime = EXCLUDED.regime,
                   updated_at = now()
                """,
                (
                    payload["global_status"],
                    payload["kr_status"],
                    indices_json,
                    macro_json,
                    payload["mv_pq_signal"],
                    dial_json,
                    payload["one_line_guidance"],
                    regime_json,
                ),
            )
    print(f"  published: global={payload['global_status']}, "
          f"dial={payload['dial_scores']}")
    print(f"  mv_pq: {payload['mv_pq_signal']}")
    print(f"  guidance: {payload['one_line_guidance']}")
    return 0


def main() -> int:
    return publish()


if __name__ == "__main__":
    sys.exit(main())
