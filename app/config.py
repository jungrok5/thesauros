"""Global config — paths, constants, knobs.

Loads project-local secrets from a `.env` file at repo root if present.
The `.env` file is gitignored; copy `.env.example` to `.env` and fill in
keys for FRED_API_KEY, etc.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Auto-load .env from repo root (no-op if absent or python-dotenv missing).
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    pass

DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
CACHE_DIR = ROOT / ".cache"
CACHE_DIR.mkdir(exist_ok=True)
MODEL_DIR = ROOT / "models_store"
MODEL_DIR.mkdir(exist_ok=True)

DUCKDB_PATH = str(DATA_DIR / "pit.duckdb")

# SEC EDGAR identification — required by SEC fair use policy
SEC_USER_AGENT = os.getenv(
    "SEC_USER_AGENT",
    "FinanceResearch jungrok5@gmail.com",
)

# FRED (Federal Reserve Economic Data) — register at https://fred.stlouisfed.org/
FRED_API_KEY = os.getenv("FRED_API_KEY", "")

# Ticker conventions:
#   US:  AAPL, MSFT     (yfinance native)
#   KR:  005930.KS (KOSPI), 035420.KQ (KOSDAQ)
def is_korean_ticker(ticker: str) -> bool:
    return ticker.endswith(".KS") or ticker.endswith(".KQ")


# Knobs
TRADING_DAYS = 252
RF_ANNUAL = 0.035

# Forward-return horizon for ML target (in trading days)
FORWARD_HORIZON = 21          # ~1 month
EMBARGO_DAYS = FORWARD_HORIZON  # Embargo gap for PurgedKFold

# Default train/test split anchor
LOOKBACK_YEARS = 8

# Top-K stocks to hold each rebalance
DEFAULT_TOP_K = 20
DEFAULT_REBALANCE_DAYS = 21

# Realistic transaction cost (bps per side)
COST_BPS = 10.0
SLIPPAGE_BPS = 5.0  # additional bps for large-cap mid-day execution
