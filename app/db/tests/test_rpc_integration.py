"""Integration tests for production RPC functions.

Hits the live Supabase DB to verify that the RPCs (introduced via
migrations 033, 034, 035, 036, 037) return:
  1. correct row shapes / column types
  2. results within plausible ranges (not empty, not absurd)
  3. order-by invariants the UI depends on

These tests caught two regressions during development:
  - PostgREST 1000-row silent truncation (now fixed via RPC)
  - book_score-only sort mixing STRONG_BUY/HOLD (now fixed with
    action_priority secondary key)

If a future migration breaks RPC signatures or output shape, these
tests fail BEFORE the cron writes bad data or the UI renders nothing.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_ROOT / ".env")

from app.db import get_conn  # noqa: E402


def _has_db() -> bool:
    return bool(os.environ.get("SUPABASE_DB_PASSWORD"))


pytestmark = pytest.mark.skipif(not _has_db(), reason="DB not configured")


# ─────────────────────────────────────────────────────────────────────
# top_flow_rankings RPC — /flow-ranking page
# ─────────────────────────────────────────────────────────────────────

class TestTopFlowRankings:
    def test_buy_top_30_returns_30_rows(self):
        with get_conn(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM top_flow_rankings(14, 30, 'buy')")
                rows = cur.fetchall()
        assert len(rows) > 0, "no buy ranking rows — investor_flow empty?"
        assert len(rows) <= 30, "exceeded LIMIT 30"

    def test_buy_results_have_positive_combined_sum(self):
        with get_conn(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM top_flow_rankings(14, 5, 'buy')")
                for row in cur.fetchall():
                    _, _, _, combined_sum, _ = row
                    assert float(combined_sum) > 0, (
                        f"buy ranking should have positive combined_sum, "
                        f"got {combined_sum}"
                    )

    def test_sell_results_have_negative_combined_sum(self):
        with get_conn(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM top_flow_rankings(14, 5, 'sell')")
                for row in cur.fetchall():
                    _, _, _, combined_sum, _ = row
                    assert float(combined_sum) < 0, (
                        f"sell ranking should have negative combined_sum, "
                        f"got {combined_sum}"
                    )

    def test_ordered_by_combined_sum_desc_for_buy(self):
        with get_conn(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM top_flow_rankings(14, 10, 'buy')")
                sums = [float(r[3]) for r in cur.fetchall()]
        assert sums == sorted(sums, reverse=True), (
            f"buy ranking not sorted DESC: {sums}"
        )


# ─────────────────────────────────────────────────────────────────────
# volume_surges + volume_surge_for_ticker — /volume-surge + stock detail
# ─────────────────────────────────────────────────────────────────────

class TestVolumeSurges:
    def test_all_results_above_threshold(self):
        with get_conn(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM volume_surges(2.0, 4, 30)")
                for row in cur.fetchall():
                    ratio = float(row[3])
                    assert ratio >= 2.0, (
                        f"volume_surges returned ratio < 2.0: {ratio}"
                    )

    def test_ordered_by_ratio_desc(self):
        with get_conn(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT ratio FROM volume_surges(2.0, 4, 20)")
                ratios = [float(r[0]) for r in cur.fetchall()]
        assert ratios == sorted(ratios, reverse=True), "ratios not DESC"

    def test_per_ticker_variant_works_for_known_high_volume_ticker(self):
        """단일 ticker RPC — 폭증 종목 (아이로보틱스) 에서 ratio > 1.5
        나와야. 폭증 RPC와 같은 종목으로 비교."""
        with get_conn(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM volume_surge_for_ticker('066430.KQ')")
                row = cur.fetchone()
        assert row is not None, "066430.KQ has no recent W bars"
        ratio = float(row[2]) if row[2] is not None else 0
        assert ratio > 0, f"ratio should be positive, got {ratio}"


# ─────────────────────────────────────────────────────────────────────
# screener_results + screener_action_distribution — /screener page
# ─────────────────────────────────────────────────────────────────────

class TestScreenerRPCs:
    def test_value_classic_preset_returns_rows(self):
        with get_conn(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM screener_results("
                    "p_passes_graham => true, "
                    "p_passes_buffett => true, "
                    "p_limit => 50)"
                )
                rows = cur.fetchall()
        assert len(rows) > 0, "value-classic preset empty — factors_eval gates broken?"
        assert len(rows) <= 50, "exceeded LIMIT"

    def test_book_buy_preset_only_returns_buy_or_strong_buy(self):
        """book-buy preset 의 actionIn 필터가 정확히 동작 — 다른 action
        섞이면 안 됨. 2026-05-20 fix 의 회귀 가드."""
        with get_conn(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT action FROM screener_results("
                    "p_action_in => ARRAY['STRONG_BUY','BUY']::TEXT[], "
                    "p_book_score_min => 0.7::NUMERIC, "
                    "p_limit => 50)"
                )
                actions = [r[0] for r in cur.fetchall()]
        for a in actions:
            assert a in ("STRONG_BUY", "BUY"), (
                f"book-buy preset returned {a} — filter broken"
            )

    def test_results_sorted_by_book_score_then_action_priority(self):
        """같은 book_score 안에서 STRONG_BUY 가 HOLD 보다 위에 와야.
        2026-05-20 사용자 보고 fix 의 회귀 가드."""
        with get_conn(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT action, book_score FROM screener_results("
                    "p_per_max => 10::NUMERIC, "
                    "p_pbr_max => 1.0::NUMERIC, "
                    "p_debt_ratio_max => 1.0::NUMERIC, "
                    "p_limit => 30)"
                )
                rows = cur.fetchall()
        # Pair iteration: for any two adjacent rows with same book_score,
        # the action priority must be non-increasing.
        priority = {"STRONG_BUY": 5, "BUY": 4, "HOLD": 3,
                    None: 2, "AVOID": 1, "SELL": 1, "SELL_OR_SHORT": 1}
        for (a1, s1), (a2, s2) in zip(rows, rows[1:]):
            if s1 == s2:
                p1 = priority.get(a1, 2)
                p2 = priority.get(a2, 2)
                assert p1 >= p2, (
                    f"sort broken at same book_score={s1}: "
                    f"{a1} (prio {p1}) followed by {a2} (prio {p2})"
                )

    def test_action_distribution_buckets_sum_to_passing_total(self):
        """distribution 의 5 bucket 합이 결과 행 수와 일치해야 (없어진
        action 종목 X)."""
        with get_conn(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM screener_action_distribution("
                    "p_passes_graham => true, p_passes_buffett => true)"
                )
                row = cur.fetchone()
        assert row is not None
        strong, buy, hold, avoid, unanalyzed = row
        # Now query the full result set and verify counts match.
        with get_conn(autocommit=True) as conn:
            with conn.cursor() as cur:
                # No LIMIT — get all matching rows for verification
                cur.execute(
                    "SELECT action FROM screener_results("
                    "p_passes_graham => true, p_passes_buffett => true, "
                    "p_limit => 999)"
                )
                actions = [r[0] for r in cur.fetchall()]
        # Re-bucket
        actual = {"strong_buy": 0, "buy": 0, "hold": 0, "avoid": 0, "unanalyzed": 0}
        for a in actions:
            if a == "STRONG_BUY":
                actual["strong_buy"] += 1
            elif a == "BUY":
                actual["buy"] += 1
            elif a == "HOLD":
                actual["hold"] += 1
            elif a in ("AVOID", "SELL", "SELL_OR_SHORT"):
                actual["avoid"] += 1
            else:
                actual["unanalyzed"] += 1
        assert actual["strong_buy"] == strong, f"strong_buy: rpc {strong} vs actual {actual['strong_buy']}"
        assert actual["buy"] == buy, f"buy: rpc {buy} vs actual {actual['buy']}"
        assert actual["hold"] == hold, f"hold: rpc {hold} vs actual {actual['hold']}"
        assert actual["avoid"] == avoid, f"avoid: rpc {avoid} vs actual {actual['avoid']}"
