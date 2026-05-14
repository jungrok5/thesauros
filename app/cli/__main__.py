"""CLI entry point — `python -m app.cli <command> [args]`."""
from __future__ import annotations

import json
import sys
from typing import Optional

# Force UTF-8 output for Korean text on Windows consoles.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import typer

app = typer.Typer(add_completion=False, help="Thesauros book-analysis CLI.")


# ---------------------------------------------------------------------------
# Macro
# ---------------------------------------------------------------------------
@app.command("macro")
def cmd_macro(
    json_out: bool = typer.Option(False, "--json", help="Output as JSON."),
):
    """Show current macro snapshot (all indicators + regime)."""
    from app.macro.state import categorized, market_regime

    regime = market_regime()
    cats = categorized()

    if json_out:
        sys.stdout.write(json.dumps({"regime": regime, "indicators": cats},
                                    ensure_ascii=False, indent=2, default=str))
        return

    print(f"\n=== 시장 레짐: {regime['regime']}  (score {regime['score']}, "
          f"n={regime['n_indicators']}) ===")
    print(f"  {regime['note']}\n")

    for cat_label, items in cats.items():
        print(f"[{cat_label}]")
        for it in items:
            v = f"{it['value']:>10.2f}" if it['value'] is not None else "    --    "
            yoy = f"{it['yoy_pct']:+.1f}%" if it['yoy_pct'] is not None else "  --  "
            print(f"  {it['state']:7s}  {it['name_kr']:<28s} {v} {it['unit']:>4s}  "
                  f"YoY {yoy}  | {it['verdict']}")
        print()


@app.command("ingest-macro")
def cmd_ingest_macro(years: int = 8):
    """Fetch all macro indicators from FRED + yfinance."""
    from app.macro.fetch import ingest_all
    print(f"Ingesting macro (years={years})...")
    counts = ingest_all(years=years, verbose=True)
    ok = sum(1 for v in counts.values() if v > 0)
    print(f"\nDone. {ok}/{len(counts)} series got new rows.")


# ---------------------------------------------------------------------------
# Stock analysis
# ---------------------------------------------------------------------------
@app.command("analyze")
def cmd_analyze(
    ticker: str = typer.Argument(..., help="e.g. AAPL or 005930.KS"),
    years: int = typer.Option(3, help="Years of history to use."),
    json_out: bool = typer.Option(False, "--json"),
):
    """Run book's trend + candle analysis on a single ticker."""
    import pandas as pd
    from app.book.trend import analyze_multi_timeframe
    from app.book.candles import latest_candle_summary, analyze_candles
    from app.data.pit_db import cursor

    with cursor() as con:
        df = con.execute(
            "SELECT date, open, high, low, close, adj_close, volume FROM prices "
            "WHERE ticker = ? ORDER BY date",
            [ticker],
        ).df()

    if df.empty:
        # Fall back to live yfinance fetch
        from datetime import date, timedelta
        import yfinance as yf
        start = (date.today() - timedelta(days=years * 365 + 30)).isoformat()
        t = yf.Ticker(ticker)
        df = t.history(start=start, auto_adjust=False, actions=False)
        if df is None or df.empty:
            typer.echo(f"No data for {ticker}.", err=True)
            raise typer.Exit(code=1)
        df = df.reset_index().rename(columns={
            "Date": "date", "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Adj Close": "adj_close", "Volume": "volume",
        })
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    mt = analyze_multi_timeframe(df)
    last_candle = latest_candle_summary(df)
    weekly_recent = analyze_candles(df.tail(120))
    last_weekly_tags = []
    # quick mini-summary of last 5 weekly candles (approx)
    from app.book.trend import resample_to_period
    weekly_df = resample_to_period(df, "W")
    weekly_candles = analyze_candles(weekly_df) if not weekly_df.empty else []
    weekly_recent_summary = [c.to_dict() for c in weekly_candles[-5:]] if weekly_candles else []

    result = {
        "ticker": ticker,
        "rows": len(df),
        "last_date": str(df["date"].iloc[-1].date()),
        "last_close": round(float(df["close"].iloc[-1]), 4),
        "trend": mt.to_dict(),
        "last_daily_candle": last_candle,
        "last_5_weekly_candles": weekly_recent_summary,
    }

    if json_out:
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return

    t = mt
    print(f"\n=== {ticker} — 분석 ({result['last_date']}, close={result['last_close']}) ===\n")
    print(f"  📊 책 시그널: {t.book_signal}")
    print(f"  📝 사유:     {t.book_reason}\n")
    for tf_name, tf in [("일봉", t.daily), ("주봉", t.weekly), ("월봉", t.monthly)]:
        if tf is None:
            print(f"  [{tf_name}] 데이터 부족")
            continue
        ma240 = f"{tf.ma_240:.2f}" if tf.ma_240 else "—"
        print(f"  [{tf_name}] {tf.label:4s}  score {tf.overall_score:+.2f}  "
              f"price {tf.price:.2f} vs 10MA {tf.ma_10:.2f} ({'위' if tf.above_ma_10 else '아래'})  "
              f"240MA {ma240}  정배열 {tf.alignment_score:+.2f}")

    if last_candle:
        print(f"\n  최근 캔들 tags: {', '.join(last_candle['tags']) or '—'}")
        if last_candle.get("in_safe_zone_75") is True:
            print(f"  ✓ 4등분선 75% 안전지대 (책: 다음 봉 상승 확률 높음)")
        elif last_candle.get("in_safe_zone_75") is False:
            print(f"  ⚠ 4등분선 75% 아래 — 추세 약화 가능")
    print()


@app.command("ingest-krx")
def cmd_ingest_krx(
    years: int = typer.Option(5, help="Years of history."),
    workers: int = typer.Option(4, help="Parallel fetchers."),
    full: bool = typer.Option(False, "--full", help="Fetch full KOSPI+KOSDAQ (slow)."),
):
    """Refresh Korean stock prices via pykrx."""
    if full:
        from app.data.ingest_krx import krx_universe, ingest
        u = krx_universe()
        print(f"Universe: {len(u)} tickers")
        ingest(u, years=years, workers=workers, verbose=True)
    else:
        from app.data.ingest_krx import ingest_kospi200_kosdaq150
        ingest_kospi200_kosdaq150(years=years, workers=workers, verbose=True)


@app.command("ingest-us")
def cmd_ingest_us(
    years: int = typer.Option(8),
    universe: str = typer.Option("sp500", help="sp500 | dow | nasdaq100"),
    workers: int = typer.Option(8),
):
    """Refresh US stock prices via yfinance."""
    from app.data.ingest_prices import ingest_universe
    from app.data.universe import sp500_tickers, dow_tickers, nasdaq100_tickers
    if universe == "sp500":
        tickers = sp500_tickers()
    elif universe == "dow":
        tickers = dow_tickers()
    elif universe == "nasdaq100":
        tickers = nasdaq100_tickers()
    else:
        typer.echo(f"unknown universe: {universe}", err=True)
        raise typer.Exit(code=1)
    print(f"Universe: {len(tickers)} tickers")
    ingest_universe(tickers, years=years, workers=workers)


@app.command("stats")
def cmd_stats():
    """Show DB stats (price + macro coverage)."""
    from app.data.pit_db import stats, cursor
    s = stats()
    print(json.dumps(s, indent=2, default=str))
    with cursor() as con:
        df = con.execute("""
            SELECT
                COUNT(DISTINCT series_id) AS series,
                COUNT(*) AS rows
            FROM macro
        """).df()
    print(f"macro: {df.iloc[0].to_dict()}")


if __name__ == "__main__":
    app()
