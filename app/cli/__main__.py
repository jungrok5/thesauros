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
    years: int = typer.Option(5, help="Years of history to use."),
    json_out: bool = typer.Option(False, "--json"),
):
    """Run full book analysis (trend + candles + patterns + volume) on a ticker."""
    from app.book.analyzer import analyze_ticker, load_ticker_data

    df = load_ticker_data(ticker, years=years)
    if df is None or df.empty:
        typer.echo(f"No data for {ticker}.", err=True)
        raise typer.Exit(code=1)

    result = analyze_ticker(ticker, df)

    if json_out:
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return

    print(f"\n=== {result['ticker']} — 분석 ({result['as_of']}, "
          f"close={result['last_close']}) ===\n")
    print(f"  🎯 액션:      {result['action']}")
    print(f"  📊 책 점수:    {result['book_score']:+.2f}  /  추세시그널: {result['trend']['book_signal']}")
    print(f"  📝 추세 사유:  {result['trend']['book_reason']}\n")

    for tf_name, tf in [("일봉", result["trend"]["daily"]),
                        ("주봉", result["trend"]["weekly"]),
                        ("월봉", result["trend"]["monthly"])]:
        if tf is None:
            print(f"  [{tf_name}] 데이터 부족")
            continue
        ma240 = f"{tf['ma_240']:.2f}" if tf.get("ma_240") else "—"
        above10 = "위" if tf["above_ma_10"] else "아래"
        print(f"  [{tf_name}] {tf['label']:4s}  score {tf['overall_score']:+.2f}  "
              f"price {tf['price']:.2f} vs 10MA {tf['ma_10']:.2f} ({above10})  "
              f"240MA {ma240}  정배열 {tf['alignment_score']:+.2f}")

    lc = result.get("last_candle")
    if lc:
        print(f"\n  최근 캔들 tags: {', '.join(lc['tags']) or '—'}")
        if lc.get("in_safe_zone_75") is True:
            print(f"  ✓ 4등분선 75% 안전지대 (책: 다음 봉 상승 확률 높음)")
        elif lc.get("in_safe_zone_75") is False:
            print(f"  ⚠ 4등분선 75% 아래 — 추세 약화 가능")

    if result["patterns"]:
        print(f"\n  📐 감지된 패턴 ({len(result['patterns'])}):")
        for p in result["patterns"][:6]:
            mark = "✓" if p["completed"] else "⋯"
            print(f"    {mark} [{p.get('timeframe', '?'):7s}] {p['kind']:<25s} "
                  f"({p['direction']:>7s}, conf {p['confidence']:.2f})")
            print(f"        {p['reason']}")

    if result["reversals"]:
        print(f"\n  ⤴ 되돌림 패턴 ({len(result['reversals'])}):")
        for r in result["reversals"][:3]:
            print(f"    [{r['direction']}] {r['kind']:<30s} conf {r['confidence']:.2f}")
            print(f"        {r['reason']}")

    vc = result.get("volume_case")
    if vc:
        print(f"\n  📊 거래량 분류: 케이스 {vc['case']} — {vc['label_kr']} "
              f"(conf {vc['confidence']:.2f}, {vc['direction']})")
        print(f"     {vc['reason']}")

    ra = result.get("reverse_accumulation")
    if ra:
        print(f"\n  ⭐ 역매집 감지: {ra['occurrences']}회 / {ra['reason']}")

    plan = result.get("entry_plan")
    if plan:
        print(f"\n  💡 매매 플랜 ({plan['based_on']}):")
        print(f"     진입: {plan['entry']}  손절: {plan['stop']}  "
              f"목표: {plan['target']}")
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


# ---------------------------------------------------------------------------
# Backtest + screen
# ---------------------------------------------------------------------------
@app.command("backtest")
def cmd_backtest(
    ticker: str = typer.Argument(...),
    strategy: str = typer.Option("monthly_10ma", help="monthly_10ma | weekly_10ma"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Backtest book's rules on a single ticker."""
    from app.book.analyzer import load_ticker_data
    from app.book.backtest import backtest_ticker

    df = load_ticker_data(ticker, years=15)
    if df is None or df.empty:
        typer.echo(f"No data for {ticker}.", err=True)
        raise typer.Exit(code=1)
    report = backtest_ticker(ticker, df, strategy=strategy)
    if json_out:
        sys.stdout.write(json.dumps(report.to_dict(), ensure_ascii=False,
                                    indent=2, default=str))
        return
    r = report
    print(f"\n=== {r.ticker} 백테스트 ({r.strategy}) — {r.period} ===")
    print(f"  거래 횟수:        {r.n_trades}")
    print(f"  승률:             {r.win_rate:.1f}%")
    print(f"  평균 수익(승리):   {r.avg_gain_winners:+.2f}%")
    print(f"  평균 손실(패배):   {r.avg_loss_losers:+.2f}%")
    print(f"  평균 거래 수익률:  {r.avg_return_pct:+.2f}%")
    print(f"  총 누적 수익률:    {r.total_return_pct:+.2f}%")
    print(f"  buy & hold 비교:  {r.buy_and_hold_return_pct:+.2f}%")
    print(f"  시장 노출 비율:    {r.bars_in_market_pct:.1f}%")
    print(f"  최악 단일 거래:    {r.max_drawdown_trade:+.2f}%")
    if r.trades and len(r.trades) <= 30:
        print(f"\n  거래 내역:")
        for t in r.trades:
            sign = "+" if (t["return_pct"] or 0) >= 0 else ""
            print(f"    {t['entry_date']} → {t['exit_date']}  "
                  f"{t['entry_price']:>10.2f} → {t['exit_price']:>10.2f}  "
                  f"{sign}{t['return_pct']:6.2f}%   ({t['exit_reason']})")
    print()


@app.command("book-cases")
def cmd_book_cases():
    """Run backtest on the book's headline example tickers."""
    from app.book.analyzer import load_ticker_data
    from app.book.backtest import backtest_ticker, BOOK_CASES
    print(f"\n=== 책 사례 검증 (월봉 10MA 룰) ===\n")
    for ticker, claim, period, strat in BOOK_CASES:
        df = load_ticker_data(ticker, years=15)
        if df is None or df.empty:
            print(f"  {ticker:<12} — 데이터 없음")
            continue
        r = backtest_ticker(ticker, df, strategy="monthly_10ma")
        claim_str = f"책 주장 +{claim}%" if claim else ""
        print(f"  {ticker:<12}  ({period})")
        print(f"     n={r.n_trades:<3d}  승률 {r.win_rate:>5.1f}%  "
              f"총수익 {r.total_return_pct:>+8.2f}%  vs B&H {r.buy_and_hold_return_pct:>+8.2f}%  "
              f"{claim_str}")


@app.command("screen")
def cmd_screen(
    market: str = typer.Option("us", help="us | kr | all"),
    min_score: float = typer.Option(0.5, help="Min book score for inclusion"),
    only_completed: bool = typer.Option(True, help="Require completed bullish pattern"),
    top: int = typer.Option(20, help="Show top N"),
):
    """Scan all stored tickers and rank by book's combined criteria."""
    from app.data.pit_db import cursor
    from app.book.analyzer import analyze_ticker
    import pandas as pd

    with cursor() as con:
        if market == "us":
            where = "ticker NOT LIKE '%.KS' AND ticker NOT LIKE '%.KQ'"
        elif market == "kr":
            where = "ticker LIKE '%.KS' OR ticker LIKE '%.KQ'"
        else:
            where = "1=1"
        tickers = [r[0] for r in con.execute(
            f"SELECT DISTINCT ticker FROM prices WHERE {where} ORDER BY ticker"
        ).fetchall()]

    print(f"Scanning {len(tickers)} tickers...")
    results = []
    for i, t in enumerate(tickers, 1):
        try:
            with cursor() as con:
                df = con.execute(
                    "SELECT date, open, high, low, close, adj_close, volume FROM prices "
                    "WHERE ticker = ? ORDER BY date", [t]
                ).df()
            if df.empty or len(df) < 250:
                continue
            df["date"] = pd.to_datetime(df["date"])
            r = analyze_ticker(t, df)
            if r["book_score"] < min_score:
                continue
            if only_completed:
                has_bull = any(p["completed"] and p["direction"] == "bullish"
                               and p["confidence"] >= 0.7 for p in r["patterns"])
                if not has_bull:
                    continue
            results.append(r)
            if i % 100 == 0:
                print(f"  ... {i}/{len(tickers)}")
        except Exception as e:
            continue

    results.sort(key=lambda x: -x["book_score"])
    print(f"\nFound {len(results)} candidates; top {top}:\n")
    for r in results[:top]:
        top_pat = r["patterns"][0]["kind"] if r["patterns"] else "—"
        print(f"  {r['ticker']:<14}  {r['action']:<11}  score {r['book_score']:+.2f}  "
              f"close {r['last_close']:>10.2f}  patterns={len(r['patterns'])}  "
              f"top={top_pat}")


if __name__ == "__main__":
    app()
