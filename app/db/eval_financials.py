"""Compute rule-based evaluations for financials + factors → Supabase.

Reads from the local DuckDB `fundamentals` table (populated by
app.data.ingest_dart / ingest_sec) and writes per-ticker rows to
`financials_eval` and `factors_eval` with:
  - 3-year time series JSONB (revenue, op income, net income, assets, debt)
  - latest single-value metrics (debt_ratio, roe, op_margin, growth, F-score)
  - rule-based evaluation strings ("🟢 우수" etc.) per threshold ranges
  - book + academia gate booleans (강환국, 그레이엄, 마법공식, 버핏)
  - 4-axis scores (value/growth/safety/quality) 0..10
  - one-paragraph summary text generated from the rules

No LLM dependency. All thresholds documented in scan_results.signal_type
naming.

Usage:
    python -m app.db.eval_financials                          # all tickers
    python -m app.db.eval_financials --tickers 005930.KS AAPL # specific
    python -m app.db.eval_financials --limit 100              # sample
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.db import get_conn   # noqa: E402

log = logging.getLogger("eval_financials")


# ---------------------------------------------------------------------------
# Rule tables — single source of truth for thresholds.
# Each rule: (predicate, label, classification_tag).
# Tag is used for composite scoring; label is shown to the user.
# ---------------------------------------------------------------------------

RULES: Dict[str, List[Tuple[Any, str, str]]] = {
    "per": [
        (lambda v: v is None or v <= 0, "🟤 적자/측정불가", "na"),
        (lambda v: v < 8,                "🟢 매우 저평가",   "deep_value"),
        (lambda v: v < 15,               "🟢 저평가",        "value"),
        (lambda v: v < 25,               "🟡 적정",          "fair"),
        (lambda v: v < 50,               "🟠 다소 고평가",   "growth"),
        (lambda v: True,                  "🔴 고평가",        "expensive"),
    ],
    "pbr": [
        (lambda v: v is None or v <= 0, "🟤 측정불가",         "na"),
        (lambda v: v < 1,                "🟢 청산가치 이하",    "deep_value"),
        (lambda v: v < 1.5,              "🟢 저평가",          "value"),
        (lambda v: v < 3,                "🟡 적정",            "fair"),
        (lambda v: True,                  "🔴 고평가",          "expensive"),
    ],
    "roe": [
        (lambda v: v is None,             "🟤 측정불가", "na"),
        (lambda v: v >= 0.20,             "🟢 탁월",     "excellent"),
        (lambda v: v >= 0.15,             "🟢 우수",     "good"),
        (lambda v: v >= 0.08,             "🟡 양호",     "ok"),
        (lambda v: v >= 0,                "🟠 미흡",     "weak"),
        (lambda v: True,                   "🔴 적자",     "loss"),
    ],
    "roa": [
        (lambda v: v is None, "🟤 측정불가", "na"),
        (lambda v: v >= 0.08, "🟢 우수",     "good"),
        (lambda v: v >= 0.05, "🟡 양호",     "ok"),
        (lambda v: v >= 0.02, "🟠 평이",     "weak"),
        (lambda v: True,       "🔴 미흡",     "loss"),
    ],
    "op_margin": [
        (lambda v: v is None, "🟤 측정불가", "na"),
        (lambda v: v >= 0.20, "🟢 우수",     "excellent"),
        (lambda v: v >= 0.08, "🟡 양호",     "good"),
        (lambda v: v >= 0.03, "🟠 평이",     "weak"),
        (lambda v: v >= 0,    "🟠 미흡",     "weak"),
        (lambda v: True,       "🔴 적자",     "loss"),
    ],
    "debt_ratio": [
        (lambda v: v is None, "🟤 측정불가", "na"),
        (lambda v: v < 0.30,  "🟢 매우 안전","excellent"),
        (lambda v: v < 0.50,  "🟢 안전",     "good"),
        (lambda v: v < 1.00,  "🟡 보통",     "fair"),
        (lambda v: v < 2.00,  "🟠 주의",     "warn"),
        (lambda v: True,       "🔴 위험",     "danger"),
    ],
    "revenue_growth_yoy": [
        (lambda v: v is None, "🟤 측정불가",   "na"),
        (lambda v: v >= 0.30, "🟢 폭발 성장",  "excellent"),
        (lambda v: v >= 0.15, "🟢 고성장",     "good"),
        (lambda v: v >= 0.05, "🟡 안정 성장",  "ok"),
        (lambda v: v >= 0,    "🟠 정체",       "weak"),
        (lambda v: True,       "🔴 역성장",     "decline"),
    ],
}


def evaluate(name: str, value: Optional[float]) -> Tuple[str, str]:
    """Returns (display_label, classification_tag)."""
    for predicate, label, tag in RULES.get(name, []):
        if predicate(value):
            return label, tag
    return "🟤 미평가", "na"


def composite_gates(metrics: Dict[str, Optional[float]]) -> Dict[str, bool]:
    per = metrics.get("per")
    pbr = metrics.get("pbr")
    roe = metrics.get("roe")
    debt = metrics.get("debt_ratio")
    op_margin = metrics.get("op_margin")
    return {
        "passes_kang_value": (
            pbr is not None and pbr > 0 and pbr < 1.5
            and roe is not None and roe > 0.10
        ),
        "passes_graham": (
            per is not None and per > 0 and per < 15
            and debt is not None and debt < 0.50
        ),
        "passes_magic_formula": (
            per is not None and per > 0 and per < 12
            and op_margin is not None and op_margin > 0.10
        ),
        "passes_buffett": (
            roe is not None and roe > 0.15
            and debt is not None and debt < 0.50
        ),
    }


# ---------- 4-axis scoring (0..10 each) ------------------------------------

def _score(value: Optional[float], breakpoints: List[float],
           reverse: bool = False) -> int:
    """Map value → 0..10 against ascending breakpoints (or descending)."""
    if value is None:
        return 0
    bps = breakpoints if not reverse else list(reversed(breakpoints))
    score = 0
    for bp in bps:
        if (not reverse and value >= bp) or (reverse and value <= bp):
            score += 1
    return min(score, 10)


def axis_scores(metrics: Dict[str, Optional[float]]) -> Dict[str, int]:
    per = metrics.get("per") or 100
    pbr = metrics.get("pbr") or 100
    roe = metrics.get("roe") or -1
    roa = metrics.get("roa") or -1
    op_margin = metrics.get("op_margin") or -1
    debt = metrics.get("debt_ratio") or 100
    growth = metrics.get("revenue_growth_yoy") or -1

    return {
        # Value: lower PER/PBR = higher score (reverse on ascending breakpoints)
        "value_score": _score(per, [50, 25, 15, 10, 8, 5], reverse=True) // 2
                       + _score(pbr, [4, 3, 2, 1.5, 1, 0.5], reverse=True) // 2,
        # Growth: revenue YoY
        "growth_score": _score(growth, [0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50, 1.0, 2.0, 5.0]),
        # Safety: lower debt = higher
        "safety_score": _score(debt, [3, 2, 1.5, 1, 0.75, 0.5, 0.3, 0.2, 0.1, 0.05], reverse=True),
        # Quality: higher ROE/ROA/op_margin
        "quality_score": (_score(roe, [0, 0.05, 0.10, 0.15, 0.20, 0.30])
                          + _score(roa, [0, 0.03, 0.05, 0.08, 0.12])
                          + _score(op_margin, [0, 0.05, 0.10, 0.15, 0.25])) // 2,
    }


# ---------- Summary text (rule-based, no LLM) ------------------------------

def build_summary(metrics: Dict[str, Optional[float]],
                  evals: Dict[str, str],
                  axis: Dict[str, int],
                  gates: Dict[str, bool]) -> str:
    parts = []
    growth = metrics.get("revenue_growth_yoy")
    if growth is not None:
        parts.append(
            f"매출 YoY {growth*100:+.1f}% — {evals.get('revenue_growth_yoy', '')}"
        )
    roe = metrics.get("roe")
    if roe is not None:
        parts.append(f"ROE {roe*100:.1f}% — {evals.get('roe', '')}")
    debt = metrics.get("debt_ratio")
    if debt is not None:
        parts.append(f"부채비율 {debt*100:.0f}% — {evals.get('debt_ratio', '')}")
    op = metrics.get("op_margin")
    if op is not None:
        parts.append(f"영업이익률 {op*100:.1f}% — {evals.get('op_margin', '')}")

    passed = [k.replace("passes_", "") for k, v in gates.items() if v]
    if passed:
        parts.append("통과 기준: " + ", ".join(passed))

    parts.append(
        "축별 점수: 가치 {v}/10, 성장 {g}/10, 안전 {s}/10, 수익 {q}/10".format(
            v=axis.get("value_score", 0), g=axis.get("growth_score", 0),
            s=axis.get("safety_score", 0), q=axis.get("quality_score", 0),
        )
    )
    return " · ".join(parts)


# ---------- Fundamentals → metrics ----------------------------------------

REVENUE_ALIASES = (
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueNet",
)


def _first(concepts: Dict[str, float], names: Tuple[str, ...]) -> Optional[float]:
    for n in names:
        v = concepts.get(n)
        if v is not None:
            return v
    return None


def _fundamentals_for(ticker: str) -> Optional[Tuple[Dict[str, Optional[float]],
                                                      Dict[int, Dict[str, float]],
                                                      List[int]]]:
    """Pull annual (FY) fundamentals only, derive metrics.

    Returns: (metrics, by_year_fy, sorted_years_desc) or None.

    Important: filters fp='FY' to avoid mixing quarterly YTD values with
    annual totals (SEC's filing structure stores both for the same
    period_end; the Q rows are year-to-date, not single-quarter).
    """
    try:
        from app.data.pit_db import cursor
    except Exception:
        return None
    try:
        with cursor() as con:
            df = con.execute(
                "SELECT concept, fy, fp, value FROM fundamentals "
                "WHERE ticker = ? AND fp = 'FY' "
                "ORDER BY fy DESC, filed_date DESC",
                [ticker],
            ).df()
    except Exception:
        return None
    if df.empty:
        return None

    by_year: Dict[int, Dict[str, float]] = {}
    for _, r in df.iterrows():
        concept = str(r["concept"])
        try:
            fy_raw = r["fy"]
            if fy_raw is None or (hasattr(fy_raw, "__class__") and fy_raw.__class__.__name__ == "NAType"):
                continue
            fy = int(fy_raw)
            val = float(r["value"])
        except Exception:
            continue
        # First seen wins (rows are ordered DESC by filed_date — most recent
        # restatement first, so the latest filing prevails).
        by_year.setdefault(fy, {}).setdefault(concept, val)

    years = sorted(by_year.keys(), reverse=True)
    if not years:
        return None
    latest_yr = years[0]
    latest = by_year[latest_yr]

    revenue = _first(latest, REVENUE_ALIASES)
    net_income = latest.get("NetIncomeLoss")
    op_income = latest.get("OperatingIncomeLoss")
    assets = latest.get("Assets")
    debt = latest.get("Liabilities")
    equity = latest.get("StockholdersEquity")

    if len(years) >= 2:
        last_rev = _first(by_year[years[0]], REVENUE_ALIASES)
        prev_rev = _first(by_year[years[1]], REVENUE_ALIASES)
        rev_growth = (last_rev / prev_rev - 1) if (last_rev and prev_rev and prev_rev > 0) else None
        last_ni = by_year[years[0]].get("NetIncomeLoss")
        prev_ni = by_year[years[1]].get("NetIncomeLoss")
        ni_growth = (last_ni / abs(prev_ni) - 1) if (last_ni and prev_ni) else None
    else:
        rev_growth = None
        ni_growth = None

    metrics: Dict[str, Optional[float]] = {
        "revenue": revenue,
        "net_income": net_income,
        "op_income": op_income,
        "assets": assets,
        "debt": debt,
        "equity": equity,
        "roe": (net_income / equity) if (net_income and equity and equity > 0) else None,
        "roa": (net_income / assets) if (net_income and assets and assets > 0) else None,
        "op_margin": (op_income / revenue) if (op_income and revenue and revenue > 0) else None,
        "debt_ratio": (debt / equity) if (debt and equity and equity > 0) else None,
        "revenue_growth_yoy": rev_growth,
        "net_income_growth_yoy": ni_growth,
        "current_ratio": None,           # need cur_assets / cur_liab (later)
        "f_score": None,
        # Valuation (PER/PBR) requires market_cap → skipped for now
        # (book #8: KR market_cap not yet loaded for historical PIT)
        "per": None,
        "pbr": None,
    }
    return metrics, by_year, years


def _revenue_series(by_year: Dict[int, Dict[str, float]], years: List[int]) -> Dict[str, float]:
    """Pull revenue across years, trying multiple SEC/DART concept names."""
    out: Dict[str, float] = {}
    for y in years[:3]:
        v = _first(by_year.get(y, {}), REVENUE_ALIASES)
        if v is not None:
            out[str(y)] = v
    return out


def _series_3y(by_year: Dict[int, Dict[str, float]], years: List[int],
               concept: str) -> Dict[str, float]:
    """Return last-3-year series for a concept as {fy_str: value}."""
    out = {}
    for y in years[:3]:
        v = by_year.get(y, {}).get(concept)
        if v is not None:
            out[str(y)] = v
    return out


# ---------- Driver ---------------------------------------------------------

def evaluate_ticker(ticker: str) -> Optional[Dict[str, Any]]:
    parsed = _fundamentals_for(ticker)
    if not parsed:
        return None
    metrics, by_year, years = parsed
    if not by_year:
        return None
    # Also keep DART-style data accessible via series builder.
    revenue_series = _revenue_series(by_year, years)

    evals = {}
    for name in ("per", "pbr", "roe", "roa", "op_margin", "debt_ratio", "revenue_growth_yoy"):
        label, _tag = evaluate(name, metrics.get(name))
        evals[name] = label

    gates = composite_gates(metrics)
    axis = axis_scores(metrics)
    summary = build_summary(metrics, evals, axis, gates)

    return {
        "ticker": ticker,
        "metrics": metrics,
        "evals": evals,
        "gates": gates,
        "axis": axis,
        "summary": summary,
        "series": {
            "revenue_3y": revenue_series,
            "operating_income_3y": _series_3y(by_year, years, "OperatingIncomeLoss"),
            "net_income_3y": _series_3y(by_year, years, "NetIncomeLoss"),
            "assets_3y": _series_3y(by_year, years, "Assets"),
            "debt_3y": _series_3y(by_year, years, "Liabilities"),
            "equity_3y": _series_3y(by_year, years, "StockholdersEquity"),
        },
    }


def publish(ticker: str, result: Dict[str, Any]) -> None:
    metrics = result["metrics"]
    evals = result["evals"]
    gates = result["gates"]
    axis = result["axis"]
    series = result["series"]

    with get_conn() as conn:
        with conn.cursor() as cur:
            # financials_eval
            cur.execute(
                """
                INSERT INTO financials_eval (
                    ticker, revenue_3y, operating_income_3y, net_income_3y,
                    assets_3y, debt_3y, equity_3y,
                    debt_ratio, roe, roa, op_margin,
                    revenue_growth_yoy, net_income_growth_yoy,
                    current_ratio, f_score,
                    rules_eval, composite_score, summary_text, updated_at
                ) VALUES (
                    %s, %s::jsonb, %s::jsonb, %s::jsonb,
                    %s::jsonb, %s::jsonb, %s::jsonb,
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s::jsonb, %s, %s, now()
                )
                ON CONFLICT (ticker) DO UPDATE SET
                    revenue_3y = EXCLUDED.revenue_3y,
                    operating_income_3y = EXCLUDED.operating_income_3y,
                    net_income_3y = EXCLUDED.net_income_3y,
                    assets_3y = EXCLUDED.assets_3y,
                    debt_3y = EXCLUDED.debt_3y,
                    equity_3y = EXCLUDED.equity_3y,
                    debt_ratio = EXCLUDED.debt_ratio,
                    roe = EXCLUDED.roe,
                    roa = EXCLUDED.roa,
                    op_margin = EXCLUDED.op_margin,
                    revenue_growth_yoy = EXCLUDED.revenue_growth_yoy,
                    net_income_growth_yoy = EXCLUDED.net_income_growth_yoy,
                    current_ratio = EXCLUDED.current_ratio,
                    f_score = EXCLUDED.f_score,
                    rules_eval = EXCLUDED.rules_eval,
                    composite_score = EXCLUDED.composite_score,
                    summary_text = EXCLUDED.summary_text,
                    updated_at = now()
                """,
                (
                    ticker,
                    json.dumps(series["revenue_3y"]),
                    json.dumps(series["operating_income_3y"]),
                    json.dumps(series["net_income_3y"]),
                    json.dumps(series["assets_3y"]),
                    json.dumps(series["debt_3y"]),
                    json.dumps(series["equity_3y"]),
                    metrics.get("debt_ratio"),
                    metrics.get("roe"),
                    metrics.get("roa"),
                    metrics.get("op_margin"),
                    metrics.get("revenue_growth_yoy"),
                    metrics.get("net_income_growth_yoy"),
                    metrics.get("current_ratio"),
                    metrics.get("f_score"),
                    json.dumps(evals, ensure_ascii=False),
                    sum(axis.values()) // len(axis) if axis else None,
                    result["summary"],
                ),
            )
            # factors_eval (subset for value/growth/safety/quality dial)
            cur.execute(
                """
                INSERT INTO factors_eval (
                    ticker, per, per_eval, pbr, pbr_eval,
                    roe, roe_eval, roa, roa_eval,
                    op_margin, op_margin_eval, debt_ratio, debt_ratio_eval,
                    revenue_growth,
                    passes_kang_value, passes_graham,
                    passes_magic_formula, passes_buffett,
                    value_score, growth_score, safety_score, quality_score,
                    summary_text, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, now()
                )
                ON CONFLICT (ticker) DO UPDATE SET
                    per = EXCLUDED.per, per_eval = EXCLUDED.per_eval,
                    pbr = EXCLUDED.pbr, pbr_eval = EXCLUDED.pbr_eval,
                    roe = EXCLUDED.roe, roe_eval = EXCLUDED.roe_eval,
                    roa = EXCLUDED.roa, roa_eval = EXCLUDED.roa_eval,
                    op_margin = EXCLUDED.op_margin, op_margin_eval = EXCLUDED.op_margin_eval,
                    debt_ratio = EXCLUDED.debt_ratio, debt_ratio_eval = EXCLUDED.debt_ratio_eval,
                    revenue_growth = EXCLUDED.revenue_growth,
                    passes_kang_value = EXCLUDED.passes_kang_value,
                    passes_graham = EXCLUDED.passes_graham,
                    passes_magic_formula = EXCLUDED.passes_magic_formula,
                    passes_buffett = EXCLUDED.passes_buffett,
                    value_score = EXCLUDED.value_score,
                    growth_score = EXCLUDED.growth_score,
                    safety_score = EXCLUDED.safety_score,
                    quality_score = EXCLUDED.quality_score,
                    summary_text = EXCLUDED.summary_text,
                    updated_at = now()
                """,
                (
                    ticker,
                    metrics.get("per"), evals.get("per"),
                    metrics.get("pbr"), evals.get("pbr"),
                    metrics.get("roe"), evals.get("roe"),
                    metrics.get("roa"), evals.get("roa"),
                    metrics.get("op_margin"), evals.get("op_margin"),
                    metrics.get("debt_ratio"), evals.get("debt_ratio"),
                    metrics.get("revenue_growth_yoy"),
                    gates["passes_kang_value"], gates["passes_graham"],
                    gates["passes_magic_formula"], gates["passes_buffett"],
                    axis["value_score"], axis["growth_score"],
                    axis["safety_score"], axis["quality_score"],
                    result["summary"],
                ),
            )


def _all_tickers_with_fundamentals(limit: Optional[int]) -> List[str]:
    """Intersect DuckDB fundamentals with Supabase tickers master.

    Avoids FK violations on financials_eval.ticker → tickers.ticker
    (older fundamentals rows reference codes that the FDR-derived tickers
    master may not include).
    """
    try:
        from app.data.pit_db import cursor
    except Exception:
        return []
    with cursor() as con:
        local = [r[0] for r in con.execute(
            "SELECT DISTINCT ticker FROM fundamentals"
        ).fetchall()]
    if not local:
        return []
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ticker FROM tickers WHERE is_active = true "
                "AND ticker = ANY(%s)", (local,)
            )
            allowed = {r[0] for r in cur.fetchall()}
    out = [t for t in local if t in allowed]
    if limit:
        out = out[: int(limit)]
    return out


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tickers", nargs="+", default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    tickers = args.tickers or _all_tickers_with_fundamentals(args.limit)
    log.info("evaluating %d tickers", len(tickers))
    t0 = time.time()
    n_ok = n_skipped = 0
    for i, t in enumerate(tickers, 1):
        try:
            result = evaluate_ticker(t)
            if not result:
                n_skipped += 1
                continue
            publish(t, result)
            n_ok += 1
        except Exception as e:
            log.warning("eval %s: %s", t, e)
            n_skipped += 1
        if i % 100 == 0:
            log.info("  [%d/%d] ok=%d skipped=%d", i, len(tickers), n_ok, n_skipped)
    log.info("done in %.1fs: ok=%d skipped=%d", time.time() - t0, n_ok, n_skipped)
    return 0


if __name__ == "__main__":
    sys.exit(main())
