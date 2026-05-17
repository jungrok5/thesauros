"""KIS (Korea Investment Securities) OpenAPI client — minimal wrapper.

KIS docs: https://apiportal.koreainvestment.com/

Current scope (stub-level):
  - OAuth token issuance + cache
  - Current price quote (FHKST01010100)
  - Daily OHLCV history (FHKST01010400)
  - Account balance query (TTTC8434R for real, VTTC8434R for vts)

Real-time websocket subscriptions and order placement endpoints are
intentionally NOT implemented here yet — those require automated trading
which we have deferred until the analysis pipeline is fully trusted.

Usage:
    from app.data.kis import KISClient
    c = KISClient()
    print(c.current_price("005930"))   # Samsung Electronics, 6-digit code
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import requests

from app.config import (
    CACHE_DIR,
    KIS_ACCOUNT_NO,
    KIS_ACCOUNT_PROD_CODE,
    KIS_APP_KEY,
    KIS_APP_SECRET,
    KIS_ENV,
    kis_base_url,
)


TOKEN_CACHE = CACHE_DIR / f"kis_token_{KIS_ENV}.json"


@dataclass
class KISToken:
    access_token: str
    expires_at: float       # epoch seconds


def _have_credentials() -> bool:
    return bool(KIS_APP_KEY and KIS_APP_SECRET)


# ---------------------------------------------------------------------------
# OAuth
# ---------------------------------------------------------------------------
def _load_cached_token() -> Optional[KISToken]:
    if not TOKEN_CACHE.exists():
        return None
    try:
        d = json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
        tok = KISToken(access_token=d["access_token"], expires_at=d["expires_at"])
        if tok.expires_at - time.time() < 60:
            return None  # about to expire
        return tok
    except Exception:
        return None


def _save_token(tok: KISToken) -> None:
    TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_CACHE.write_text(
        json.dumps({"access_token": tok.access_token,
                    "expires_at": tok.expires_at}),
        encoding="utf-8",
    )


def issue_token() -> KISToken:
    """OAuth client_credentials flow. Caches token for ~24h reuse."""
    if not _have_credentials():
        raise RuntimeError(
            "KIS_APP_KEY / KIS_APP_SECRET not set. Update .env or env vars."
        )
    cached = _load_cached_token()
    if cached:
        return cached

    url = f"{kis_base_url()}/oauth2/tokenP"
    payload = {
        "grant_type": "client_credentials",
        "appkey": KIS_APP_KEY,
        "appsecret": KIS_APP_SECRET,
    }
    res = requests.post(url, json=payload, timeout=10)
    res.raise_for_status()
    data = res.json()
    tok = KISToken(
        access_token=data["access_token"],
        expires_at=time.time() + int(data.get("expires_in", 86400)) - 60,
    )
    _save_token(tok)
    return tok


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
class KISClient:
    """Thin wrapper around the KIS REST endpoints we currently use."""

    def __init__(self):
        if not _have_credentials():
            raise RuntimeError("KIS credentials missing — see app/config.py.")
        self.base = kis_base_url()
        self.token = issue_token()

    def _headers(self, tr_id: str, hashkey: Optional[str] = None) -> Dict[str, str]:
        h = {
            "authorization": f"Bearer {self.token.access_token}",
            "appkey": KIS_APP_KEY,
            "appsecret": KIS_APP_SECRET,
            "tr_id": tr_id,
            "Content-Type": "application/json; charset=utf-8",
        }
        if hashkey:
            h["hashkey"] = hashkey
        return h

    # ----- quotes -----
    def current_price(self, code: str) -> Dict:
        """Current price snapshot for a single KR ticker (6-digit code)."""
        path = "/uapi/domestic-stock/v1/quotations/inquire-price"
        url = f"{self.base}{path}"
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code}
        res = requests.get(url, headers=self._headers("FHKST01010100"),
                           params=params, timeout=10)
        res.raise_for_status()
        return res.json()

    def ohlcv_daily(self, code: str, count: int = 100) -> List[Dict]:
        """Daily OHLCV history (most recent first)."""
        path = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
        url = f"{self.base}{path}"
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": code,
            "FID_PERIOD_DIV_CODE": "D",        # D=일, W=주, M=월
            "FID_ORG_ADJ_PRC": "1",            # 1=수정주가, 0=원주가
        }
        res = requests.get(url, headers=self._headers("FHKST03010100"),
                           params=params, timeout=10)
        res.raise_for_status()
        return res.json().get("output2", [])[:count]

    def investor_flow(self, code: str) -> List[Dict]:
        """일별 외국인/기관/개인 매매 동향 (recent 30 trading days).

        KIS endpoint: /uapi/domestic-stock/v1/quotations/inquire-investor
        TR-ID: FHKST01010900

        Returns list of dicts; relevant fields per row:
          stck_bsop_date    YYYYMMDD
          frgn_ntby_qty     외국인 순매수 수량
          frgn_ntby_tr_pbmn 외국인 순매수 거래대금 (KRW)
          orgn_ntby_qty     기관 순매수 수량
          orgn_ntby_tr_pbmn 기관 순매수 거래대금
          prsn_ntby_qty     개인 순매수 수량
          prsn_ntby_tr_pbmn 개인 순매수 거래대금
        """
        path = "/uapi/domestic-stock/v1/quotations/inquire-investor"
        url = f"{self.base}{path}"
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code}
        res = requests.get(url, headers=self._headers("FHKST01010900"),
                           params=params, timeout=10)
        res.raise_for_status()
        return res.json().get("output", [])

    # ----- account -----
    def balance(self) -> Dict:
        """Account balance (positions + cash)."""
        if not KIS_ACCOUNT_NO:
            raise RuntimeError("KIS_ACCOUNT_NO not set.")
        tr_id = "TTTC8434R" if KIS_ENV == "real" else "VTTC8434R"
        path = "/uapi/domestic-stock/v1/trading/inquire-balance"
        url = f"{self.base}{path}"
        params = {
            "CANO": KIS_ACCOUNT_NO,
            "ACNT_PRDT_CD": KIS_ACCOUNT_PROD_CODE,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "01",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        res = requests.get(url, headers=self._headers(tr_id), params=params,
                           timeout=15)
        res.raise_for_status()
        return res.json()


# ---------------------------------------------------------------------------
# Convenience smoke test
# ---------------------------------------------------------------------------
def smoke_test() -> None:
    """Quick sanity check — issue token, fetch Samsung price."""
    print(f"KIS_ENV = {KIS_ENV}")
    print(f"base    = {kis_base_url()}")
    if not _have_credentials():
        print("(skipped: credentials missing)")
        return
    c = KISClient()
    print(f"token   = {c.token.access_token[:20]}…")
    px = c.current_price("005930")
    out = px.get("output", {})
    print(f"Samsung price: {out.get('stck_prpr')}  vol={out.get('acml_vol')}")


if __name__ == "__main__":
    smoke_test()
