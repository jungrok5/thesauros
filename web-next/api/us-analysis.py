"""Vercel Python serverless endpoint: /api/us-analysis

Phase 6 ad-hoc US ticker analysis. Calls app.data.us_analyze which
handles Tiingo fetch + cache + book pipeline.

Request:
    GET /api/us-analysis?ticker=AAPL
    POST /api/us-analysis  body={"ticker":"AAPL"}

Response (200):
    {
      "ticker": "AAPL",
      "fetched_now": true,
      "bars_count": 261,
      "first_bar": "2021-05-24",
      "last_bar": "2026-05-22",
      "meta": {"name": "Apple Inc.", "exchange": "NASDAQ", ...},
      "analysis": { ... full book pipeline result ... }
    }

Errors (4xx/5xx):
    { "error": "<message>" }

Login is enforced at the Next.js middleware/proxy layer (this file
does not re-auth).
"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

# Vercel mounts the repo root as the working dir, but Python serverless
# runs from /var/task. Add the project root (sibling of web-next) to
# sys.path so `from app.data.us_analyze import ...` resolves.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from app.data.us_analyze import analyze_us_ticker          # noqa: E402
from app.data.us_bars_tiingo import TiingoError            # noqa: E402


class handler(BaseHTTPRequestHandler):     # Vercel requires lowercase `handler`
    def do_GET(self) -> None:
        qs = parse_qs(urlparse(self.path).query)
        ticker = (qs.get("ticker", [""])[0] or "").strip()
        self._respond(ticker)

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length") or "0")
        body = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(body or b"{}")
            ticker = (payload.get("ticker") or "").strip()
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid JSON body"})
            return
        self._respond(ticker)

    def _respond(self, ticker: str) -> None:
        if not ticker:
            self._json(400, {"error": "ticker required"})
            return
        try:
            result = analyze_us_ticker(ticker)
        except TiingoError as e:
            self._json(502, {"error": f"data source: {e}"})
            return
        except ValueError as e:
            self._json(400, {"error": str(e)})
            return
        except Exception as e:
            self._json(500, {"error": f"analysis failed: {e}"})
            return
        self._json(200, result)

    def _json(self, status: int, body: dict) -> None:
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)
