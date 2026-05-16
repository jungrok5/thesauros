"""KR 종목 필터 — Gemini/한국 시장 best practice.

Gemini 가이드 (2026-05-16):
  - 관리종목/투자유의/환기종목 제외 (상폐 위험)
  - 금융주/은행/보험/지주 제외 (재무 구조 다름)
  - 스팩(SPAC) / 우선주 제외 (거래량 왜곡)
  - 거래대금 필터 (최근 20일 평균 ≥ 1억)
  - 시가총액 필터 (소형주 vs 대형주 분리)

PIT 안전: 매 시점 t 에서 그 당시 status 만 사용 (현재 상태로 과거 backtest 금지).
"""
from __future__ import annotations

from typing import List, Optional, Set

import pandas as pd


# 우선주 패턴: 끝 4자리가 5/7로 끝나는 6자리 코드 (예: 005935, 051915)
# 일반 보통주는 끝이 0
def is_preferred_stock(symbol: str) -> bool:
    """우선주 여부 (6자리 숫자 코드 끝자리로 판정)."""
    if not symbol or len(symbol) < 6:
        return False
    code = symbol.split(".")[0]
    if not code.isdigit() or len(code) != 6:
        return False
    last = code[-1]
    # 0: 보통주, 5/7: 우선주
    return last in ("5", "7")


def is_spac(name: str) -> bool:
    """스팩 (SPAC) 여부."""
    if not name:
        return False
    return ("스팩" in name) or ("SPAC" in name.upper())


def is_holding_or_financial(name: str) -> bool:
    """지주/금융/은행/증권/보험 여부 (이름 기반 휴리스틱)."""
    if not name:
        return False
    keywords = [
        "지주", "홀딩스", "Holdings",
        "은행", "Bank", "금융", "Financial",
        "증권", "Securities",
        "보험", "Insurance",
        "캐피탈", "Capital",
        "신용카드", "Card",
        "투자", "Investment",  # 투자회사
    ]
    return any(k.lower() in name.lower() for k in keywords)


def filter_kr_universe(
    tickers: List[str],
    names: Optional[dict] = None,            # ticker → name
    exclude_preferred: bool = True,
    exclude_spac: bool = True,
    exclude_financial: bool = True,
    min_daily_value_krw: Optional[float] = None,   # e.g. 100_000_000 (1억)
    market_cap_percentile: Optional[tuple] = None,  # (0.0, 0.3) for bottom 30%
    asof_date: Optional[str] = None,         # PIT — only known status as of date
) -> List[str]:
    """Filter a list of KR tickers per universe selection rules.

    Args:
        tickers: list of ticker codes (e.g. ['005930.KS', ...])
        names: optional dict ticker → name (for SPAC/financial check)
        exclude_preferred: drop 우선주 (last digit 5/7)
        exclude_spac: drop 스팩
        exclude_financial: drop 지주/금융/은행/증권/보험
        min_daily_value_krw: drop low-liquidity (avg ≥ 20d). DB lookup required.
        market_cap_percentile: (lo, hi) — keep tickers in this market-cap percentile.
        asof_date: PIT date for status lookup (default = latest)
    """
    out = []
    for tk in tickers:
        if exclude_preferred and is_preferred_stock(tk):
            continue
        name = (names or {}).get(tk, "")
        if exclude_spac and is_spac(name):
            continue
        if exclude_financial and is_holding_or_financial(name):
            continue
        out.append(tk)

    # Daily value filter (requires DB query)
    if min_daily_value_krw and out:
        from app.data.pit_db import cursor
        asof = asof_date or "2024-12-31"
        with cursor() as con:
            keep = []
            for tk in out:
                r = con.execute(
                    "SELECT AVG(close * volume) FROM prices "
                    "WHERE ticker = ? AND date <= ? AND date >= date_sub(?, INTERVAL 30 DAY)",
                    [tk, asof, asof],
                ).fetchone()
                avg_val = r[0] if r and r[0] else 0
                if avg_val and avg_val >= min_daily_value_krw:
                    keep.append(tk)
            out = keep

    # Market cap percentile filter (requires shares_out — DART)
    if market_cap_percentile and out:
        from app.data.pit_db import cursor
        asof = asof_date or "2024-12-31"
        with cursor() as con:
            # Get latest price × shares_out per ticker
            df = con.execute("""
                SELECT p.ticker, p.close * f.value as mcap
                FROM prices p
                JOIN fundamentals f ON p.ticker = f.ticker
                WHERE p.date = (SELECT MAX(date) FROM prices WHERE ticker = p.ticker AND date <= ?)
                  AND f.concept = 'shares_outstanding'
                  AND f.filed_date <= ?
                  AND f.period_end = (
                      SELECT MAX(period_end) FROM fundamentals
                      WHERE ticker = f.ticker AND concept = 'shares_outstanding'
                        AND filed_date <= ?
                  )
                  AND p.ticker = ANY(?)
            """, [asof, asof, asof, out]).df()
            if not df.empty:
                lo_q = df["mcap"].quantile(market_cap_percentile[0])
                hi_q = df["mcap"].quantile(market_cap_percentile[1])
                keep_tickers = set(
                    df[(df["mcap"] >= lo_q) & (df["mcap"] <= hi_q)]["ticker"].tolist()
                )
                out = [t for t in out if t in keep_tickers]
    return out


def get_kr_universe_filtered(
    asof_date: str = "2024-12-31",
    include_delisted: bool = True,
    **filter_kwargs,
) -> List[str]:
    """Convenience: load KR tickers + names + apply filters."""
    from app.data.pit_db import cursor

    with cursor() as con:
        # Get all KR tickers in prices
        all_tickers = [r[0] for r in con.execute(
            "SELECT DISTINCT ticker FROM prices "
            "WHERE ticker LIKE '%.KS' OR ticker LIKE '%.KQ'"
        ).fetchall()]
        # Try to get names from delisted_tickers + (fund table maybe)
        names = {}
        try:
            for r in con.execute(
                "SELECT ticker, name FROM delisted_tickers"
            ).fetchall():
                names[r[0]] = r[1]
        except Exception:
            pass
        # Live names (from a names table if exists, or skip)
        try:
            for r in con.execute(
                "SELECT ticker, name FROM kr_meta"
            ).fetchall():
                names[r[0]] = r[1]
        except Exception:
            pass

        # Apply delisted filter
        if not include_delisted:
            try:
                delisted_before = set(r[0] for r in con.execute(
                    "SELECT ticker FROM delisted_tickers WHERE delisting_date <= ?",
                    [asof_date],
                ).fetchall())
                all_tickers = [t for t in all_tickers if t not in delisted_before]
            except Exception:
                pass

    return filter_kr_universe(
        all_tickers, names=names, asof_date=asof_date, **filter_kwargs
    )


if __name__ == "__main__":
    # Quick test
    print("=== KR universe filter test ===")
    universe = get_kr_universe_filtered(
        exclude_preferred=True,
        exclude_spac=True,
        exclude_financial=True,
    )
    print(f"After filter: {len(universe)} tickers")
    print(f"Sample: {universe[:10]}")
