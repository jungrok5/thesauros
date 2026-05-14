"""Book + macro API router.

Endpoints (all under /api/book/* and /api/macro/*):
  GET  /api/book/analyze?ticker=X      — full book analysis
  GET  /api/book/screen                — top candidates by book criteria
  POST /api/book/backtest              — single-ticker book-rules backtest
  GET  /api/book/cases                 — book's headline examples validated

  GET  /api/macro                      — full macro snapshot (regime + all indicators)
  GET  /api/macro/regime               — overall regime only
  GET  /api/macro/indicators           — catalog (key, name, category, desc)
  GET  /api/macro/series/{key}?years=N — single indicator's time series
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any, List, Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel


router = APIRouter(prefix="/api")


def _clean(o: Any) -> Any:
    """Recursively make a structure JSON-safe (no NaN/Inf, isoformat dates)."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(x) for x in o]
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    if isinstance(o, (pd.Timestamp, date)):
        return o.isoformat() if hasattr(o, "isoformat") else str(o)
    if isinstance(o, np.generic):
        v = o.item()
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        return v
    return o


# ----------------------------------------------------------------------------
# Book endpoints
# ----------------------------------------------------------------------------
@router.get("/book/analyze")
def analyze_ticker(ticker: str = Query(..., description="e.g. AAPL or 005930.KS"),
                   years: int = Query(5, ge=1, le=20)):
    """Run the full book pipeline on one ticker."""
    from app.book.analyzer import analyze_ticker as _analyze, load_ticker_data

    df = load_ticker_data(ticker, years=years)
    if df is None or df.empty:
        raise HTTPException(404, f"No price data for {ticker}.")
    try:
        result = _analyze(ticker, df)
    except Exception as e:
        raise HTTPException(500, f"Analysis failed: {e}")
    return JSONResponse(_clean(result))


@router.get("/book/screen")
def screen(
    market: str = Query("all", regex="^(us|kr|all)$"),
    min_score: float = Query(0.5, ge=-1.0, le=1.0),
    require_completed: bool = Query(True),
    top: int = Query(50, ge=1, le=200),
):
    """Scan the prices DB and return top book-scored tickers."""
    from app.data.pit_db import cursor
    from app.book.analyzer import analyze_ticker as _analyze

    with cursor() as con:
        if market == "us":
            where = "ticker NOT LIKE '%.KS' AND ticker NOT LIKE '%.KQ'"
        elif market == "kr":
            where = "ticker LIKE '%.KS' OR ticker LIKE '%.KQ'"
        else:
            where = "1=1"
        tickers = [
            r[0] for r in con.execute(
                f"SELECT DISTINCT ticker FROM prices WHERE {where} ORDER BY ticker"
            ).fetchall()
        ]

    results = []
    for t in tickers:
        try:
            with cursor() as con:
                df = con.execute(
                    "SELECT date, open, high, low, close, adj_close, volume FROM prices "
                    "WHERE ticker = ? ORDER BY date", [t]
                ).df()
            if df.empty or len(df) < 250:
                continue
            df["date"] = pd.to_datetime(df["date"])
            r = _analyze(t, df)
            if r["book_score"] < min_score:
                continue
            if require_completed:
                has_bull = any(
                    p["completed"] and p["direction"] == "bullish"
                    and p["confidence"] >= 0.7
                    for p in r["patterns"]
                )
                if not has_bull:
                    continue
            # Trim payload — keep only what the UI needs in the list
            results.append({
                "ticker": r["ticker"],
                "action": r["action"],
                "book_score": r["book_score"],
                "last_close": r["last_close"],
                "as_of": r["as_of"],
                "trend_signal": r["trend"]["book_signal"],
                "trend_reason": r["trend"]["book_reason"],
                "n_patterns": len(r["patterns"]),
                "top_pattern": (
                    r["patterns"][0]["kind"] if r["patterns"] else None
                ),
                "top_pattern_confidence": (
                    r["patterns"][0]["confidence"] if r["patterns"] else None
                ),
                "top_pattern_timeframe": (
                    r["patterns"][0].get("timeframe") if r["patterns"] else None
                ),
                "entry_plan": r.get("entry_plan"),
            })
        except Exception:
            continue

    results.sort(key=lambda x: -x["book_score"])
    return JSONResponse(_clean({
        "market": market,
        "min_score": min_score,
        "total_scanned": len(tickers),
        "n_candidates": len(results),
        "items": results[:top],
    }))


class BookBacktestRequest(BaseModel):
    ticker: str
    strategy: str = "monthly_10ma"   # monthly_10ma | weekly_10ma


@router.post("/book/backtest")
def book_backtest(req: BookBacktestRequest):
    from app.book.analyzer import load_ticker_data
    from app.book.backtest import backtest_ticker

    df = load_ticker_data(req.ticker, years=15)
    if df is None or df.empty:
        raise HTTPException(404, f"No data for {req.ticker}")
    report = backtest_ticker(req.ticker, df, strategy=req.strategy)
    return JSONResponse(_clean(report.to_dict()))


@router.get("/book/cases")
def book_cases():
    """Validate book's headline cases (카카오, 피에스케이홀딩스, etc.)."""
    from app.book.analyzer import load_ticker_data
    from app.book.backtest import backtest_ticker, BOOK_CASES

    items = []
    for ticker, claim, period, strat in BOOK_CASES:
        df = load_ticker_data(ticker, years=15)
        if df is None or df.empty:
            items.append({"ticker": ticker, "claim_period": period,
                          "claim_pct": claim, "error": "no data"})
            continue
        r = backtest_ticker(ticker, df, strategy="monthly_10ma")
        items.append({
            "ticker": ticker,
            "claim_period": period,
            "book_claim_pct": claim,
            "n_trades": r.n_trades,
            "win_rate_pct": r.win_rate,
            "total_return_pct": r.total_return_pct,
            "buy_and_hold_return_pct": r.buy_and_hold_return_pct,
            "max_drawdown_trade_pct": r.max_drawdown_trade,
            "bars_in_market_pct": r.bars_in_market_pct,
        })
    return JSONResponse(_clean({"items": items}))


# ----------------------------------------------------------------------------
# Macro endpoints
# ----------------------------------------------------------------------------
@router.get("/macro")
def macro_snapshot():
    """Full macro snapshot: regime + categorized indicator states."""
    from app.macro.state import market_regime, categorized
    regime = market_regime()
    indicators = categorized()
    return JSONResponse(_clean({"regime": regime, "indicators": indicators}))


@router.get("/macro/regime")
def macro_regime():
    from app.macro.state import market_regime
    return JSONResponse(_clean(market_regime()))


@router.get("/macro/indicators")
def macro_indicators_catalog():
    """Static catalog of all indicators (no live data)."""
    from app.macro.indicators import INDICATORS, CATEGORY_ORDER, CATEGORY_LABEL_KR
    return JSONResponse(_clean({
        "categories": [
            {"key": c, "label_kr": CATEGORY_LABEL_KR[c]}
            for c in CATEGORY_ORDER
        ],
        "indicators": [
            {k: v for k, v in i.items() if k != "thresholds"}
            for i in INDICATORS
        ],
    }))


@router.get("/macro/series/{key}")
def macro_series(key: str, years: int = Query(5, ge=1, le=20)):
    """Time series for one indicator + book interpretation."""
    from app.macro.indicators import INDICATORS
    from app.macro.fetch import history
    from app.macro.state import state_for

    ind = next((i for i in INDICATORS if i["key"] == key), None)
    if ind is None:
        raise HTTPException(404, f"unknown indicator: {key}")
    hist = history(ind["series_id"], years=years)
    series = [
        {"date": str(r["date"]), "value": float(r["value"])}
        for _, r in hist.iterrows()
    ]
    state = state_for(key)
    return JSONResponse(_clean({
        "key": key,
        "name_kr": ind["name_kr"],
        "desc": ind["desc"],
        "book_ref": ind["book_ref"],
        "unit": ind["unit"],
        "category": ind["category"],
        "series": series,
        "current_state": state.to_dict() if state else None,
    }))
