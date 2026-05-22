"""Unit tests for app.backtest.local_store.

DuckDB store roundtrip + dispatch routing. Each test uses a temp DB
(tmp_path fixture) so no global state contamination.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from app.backtest import local_store as LS


def _sample_bars(ticker: str = "TEST.KS") -> pd.DataFrame:
    """Three weekly bars + two monthly bars for one ticker."""
    return pd.DataFrame([
        {"granularity": "W", "bar_date": date(2024, 1, 5),
         "open": 100, "high": 105, "low": 99, "close": 103,
         "adj_close": 103, "volume": 1_000_000},
        {"granularity": "W", "bar_date": date(2024, 1, 12),
         "open": 103, "high": 110, "low": 102, "close": 108,
         "adj_close": 108, "volume": 1_500_000},
        {"granularity": "W", "bar_date": date(2024, 1, 19),
         "open": 108, "high": 115, "low": 107, "close": 112,
         "adj_close": 112, "volume": 1_200_000},
        {"granularity": "M", "bar_date": date(2024, 1, 31),
         "open": 100, "high": 120, "low": 95, "close": 115,
         "adj_close": 115, "volume": 5_000_000},
        {"granularity": "M", "bar_date": date(2024, 2, 29),
         "open": 115, "high": 130, "low": 110, "close": 125,
         "adj_close": 125, "volume": 6_000_000},
    ])


def test_schema_created_on_connect(tmp_path: Path) -> None:
    db = tmp_path / "t.duckdb"
    with LS.connect(db) as conn:
        # Tables should exist after connect with write access.
        tables = {r[0] for r in conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchall()}
    assert "bars" in tables
    assert "ingest_log" in tables


def test_upsert_then_load_roundtrip(tmp_path: Path) -> None:
    db = tmp_path / "t.duckdb"
    with LS.connect(db) as conn:
        n = LS.upsert_bars(conn, "TEST.KS", _sample_bars())
    assert n == 5
    df_w = LS.load_bars("TEST.KS", granularity="W", db_path=db)
    assert len(df_w) == 3
    assert list(df_w["close"]) == [103, 108, 112]
    df_m = LS.load_bars("TEST.KS", granularity="M", db_path=db)
    assert len(df_m) == 2


def test_upsert_replaces_duplicates(tmp_path: Path) -> None:
    """Insert once, insert again with same PK but new close → load
    reads the SECOND value (INSERT OR REPLACE semantics)."""
    db = tmp_path / "t.duckdb"
    with LS.connect(db) as conn:
        LS.upsert_bars(conn, "TEST.KS", _sample_bars())
        # Second pass with a modified close on bar 2024-01-05
        df2 = _sample_bars()
        df2.loc[0, "close"] = 999.0
        LS.upsert_bars(conn, "TEST.KS", df2)
    df = LS.load_bars("TEST.KS", granularity="W", db_path=db)
    assert df.iloc[0]["close"] == 999.0


def test_load_date_window(tmp_path: Path) -> None:
    db = tmp_path / "t.duckdb"
    with LS.connect(db) as conn:
        LS.upsert_bars(conn, "TEST.KS", _sample_bars())
    df = LS.load_bars(
        "TEST.KS", granularity="W",
        start=date(2024, 1, 10), end=date(2024, 1, 15),
        db_path=db,
    )
    assert len(df) == 1
    assert df.iloc[0]["close"] == 108


def test_load_returns_empty_for_missing_ticker(tmp_path: Path) -> None:
    db = tmp_path / "t.duckdb"
    with LS.connect(db) as conn:
        LS.upsert_bars(conn, "TEST.KS", _sample_bars())
    df = LS.load_bars("NONE.KS", granularity="W", db_path=db)
    assert df.empty


def test_load_returns_empty_when_db_missing(tmp_path: Path) -> None:
    """If the DB file doesn't exist at all, load_bars returns empty
    (no exception). Important so backtest can fall through to Supabase."""
    db = tmp_path / "does-not-exist.duckdb"
    df = LS.load_bars("ANY.KS", db_path=db)
    assert df.empty


def test_record_ingest_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "t.duckdb"
    with LS.connect(db) as conn:
        LS.record_ingest(conn, "A", source="fdr", n_bars=100)
        LS.record_ingest(conn, "A", source="yfinance", n_bars=200)
        rows = conn.execute("SELECT * FROM ingest_log WHERE ticker='A'").fetchall()
    assert len(rows) == 1     # idempotent — second call replaced
    assert rows[0][2] == "yfinance"   # source column (after ticker, ts)


def test_list_ingested_tickers(tmp_path: Path) -> None:
    db = tmp_path / "t.duckdb"
    with LS.connect(db) as conn:
        LS.upsert_bars(conn, "AAA.KS", _sample_bars("AAA.KS"))
        LS.upsert_bars(conn, "BBB.KS", _sample_bars("BBB.KS"))
        ts = LS.list_ingested_tickers(conn)
    assert ts == {"AAA.KS", "BBB.KS"}


def test_store_stats_empty(tmp_path: Path) -> None:
    db = tmp_path / "absent.duckdb"
    s = LS.store_stats(db)
    assert s.n_tickers == 0
    assert s.earliest is None


def test_store_stats_populated(tmp_path: Path) -> None:
    db = tmp_path / "t.duckdb"
    with LS.connect(db) as conn:
        LS.upsert_bars(conn, "T1.KS", _sample_bars())
        LS.upsert_bars(conn, "T2.KS", _sample_bars())
    s = LS.store_stats(db)
    assert s.n_tickers == 2
    assert s.n_bars_total == 10    # 5 rows × 2 tickers
    assert s.n_bars_W == 6
    assert s.n_bars_M == 4
    assert s.earliest == date(2024, 1, 5)
    assert s.latest == date(2024, 2, 29)


# ─────────────────────────────────────────────────────────────────────
# Dispatch — load_weekly_bars routes to local when BARS_SOURCE=local
# ─────────────────────────────────────────────────────────────────────

def test_load_weekly_bars_explicit_local_no_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    """BARS_SOURCE=local + empty local store → return empty df,
    do NOT fall through to Supabase (avoids DB calls in CI without env)."""
    from app.backtest import single_signal as SS
    monkeypatch.setenv("BARS_SOURCE", "local")
    monkeypatch.setattr(SS, "_load_from_local",
                        lambda _t: pd.DataFrame())
    # If fallback happened, _load_from_db would raise (no DB).
    monkeypatch.setattr(SS, "_load_from_db",
                        lambda _t: (_ for _ in ()).throw(
                            AssertionError("should not be called")
                        ))
    df = SS.load_weekly_bars("ANY.KS")
    assert df.empty


def test_load_weekly_bars_auto_local_then_db(monkeypatch) -> None:
    """BARS_SOURCE unset → 'auto' — try local, fall back to db
    when local is empty."""
    from app.backtest import single_signal as SS
    monkeypatch.delenv("BARS_SOURCE", raising=False)
    monkeypatch.setattr(SS, "_load_from_local",
                        lambda _t: pd.DataFrame())
    sentinel = pd.DataFrame({"date": [pd.Timestamp("2024-01-05")],
                             "close": [100]})
    monkeypatch.setattr(SS, "_load_from_db", lambda _t: sentinel)
    df = SS.load_weekly_bars("ANY.KS")
    assert len(df) == 1
    assert df.iloc[0]["close"] == 100


def test_load_weekly_bars_auto_local_hit_skips_db(monkeypatch) -> None:
    """When local has data, db must NOT be called (perf — avoid DB hit)."""
    from app.backtest import single_signal as SS
    monkeypatch.delenv("BARS_SOURCE", raising=False)
    local_df = pd.DataFrame({"date": [pd.Timestamp("2024-01-05")],
                             "close": [200]})
    monkeypatch.setattr(SS, "_load_from_local", lambda _t: local_df)
    monkeypatch.setattr(SS, "_load_from_db",
                        lambda _t: (_ for _ in ()).throw(
                            AssertionError("should not be called")
                        ))
    df = SS.load_weekly_bars("ANY.KS")
    assert df.iloc[0]["close"] == 200
