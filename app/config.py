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

# SEC EDGAR identification — required by SEC fair use policy.
# Format: "<App or your name> <your-email>". Set in .env. Public repo,
# so the default here is a placeholder — replace it via SEC_USER_AGENT
# env var. SEC will rate-limit / 403 if missing the email portion.
SEC_USER_AGENT = os.getenv(
    "SEC_USER_AGENT",
    "FinanceResearch contact@example.com",
)

# FRED (Federal Reserve Economic Data) — register at https://fred.stlouisfed.org/
FRED_API_KEY = os.getenv("FRED_API_KEY", "")

# KIS — Korea Investment Securities OpenAPI
# Register at https://apiportal.koreainvestment.com/
KIS_APP_KEY = os.getenv("KIS_APP_KEY", "")
KIS_APP_SECRET = os.getenv("KIS_APP_SECRET", "")
KIS_ACCOUNT_NO = os.getenv("KIS_ACCOUNT_NO", "")
KIS_ACCOUNT_PROD_CODE = os.getenv("KIS_ACCOUNT_PROD_CODE", "01")
KIS_ENV = os.getenv("KIS_ENV", "real")  # "real" or "vts"


def kis_base_url() -> str:
    """KIS API base URL — production vs paper-trading."""
    if KIS_ENV == "vts":
        return "https://openapivts.koreainvestment.com:29443"
    return "https://openapi.koreainvestment.com:9443"


# DART OpenAPI — Korean corporate fundamental disclosures
# Register at https://opendart.fss.or.kr/  (free, 1000 req/min)
DART_API_KEY = os.getenv("DART_API_KEY", "")
DART_BASE_URL = "https://opendart.fss.or.kr/api"


# Ticker conventions:
#   US:  AAPL, MSFT     (yfinance native)
#   KR:  005930.KS (KOSPI), 035420.KQ (KOSDAQ)
def is_korean_ticker(ticker: str) -> bool:
    return ticker.endswith(".KS") or ticker.endswith(".KQ")


# Knobs
TRADING_DAYS = 252
RF_ANNUAL = 0.035

# Default lookback for daily-bar ingest (in years)
LOOKBACK_YEARS = 8
