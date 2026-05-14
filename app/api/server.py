"""FastAPI v2 — surface the ML pipeline.

Endpoints:
  GET  /api/health
  GET  /api/data/stats           — DB row counts
  GET  /api/universe             — full S&P 500
  GET  /api/recommend?top_k=     — latest model predictions, top K
  GET  /api/analyze?ticker=      — single-ticker breakdown (features, prediction, plan)
  GET  /api/prices?ticker=&start=&end=
  POST /api/backtest             — walk-forward with optional knobs
  GET  /api/model/info           — feature importance, OOF IC stats
  POST /api/train                — retrain (long-running; returns IC summary)
"""
from __future__ import annotations

import math
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.api.book_api import router as book_router
from app.backtest.walkforward import WFParams, run_walkforward
from app.backtest.walkforward_v3 import WFv3Params, run_wf_v3
from app.config import COST_BPS, FORWARD_HORIZON, MODEL_DIR, SLIPPAGE_BPS
from app.data.pit_db import cursor, stats as db_stats
from app.data.universe import get_active_tickers, get_universe_df
from app.features.pipeline import ALL_FEATURES, build_panel, load_prices_wide
from app.model.lgbm import load_model, predict

ROOT = Path(__file__).resolve().parent.parent.parent
WEB_DIR = ROOT / "web"


app = FastAPI(title="Thesauros — Book + ML Quant", version="3.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=False,
    allow_methods=["*"], allow_headers=["*"],
)
app.include_router(book_router)


def _clean(o: Any) -> Any:
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


@app.get("/api/health")
def health():
    return {"ok": True, "today": str(date.today())}


@app.get("/api/data/stats")
def data_stats():
    return _clean(db_stats())


@app.get("/api/universe")
def universe():
    df = get_universe_df()
    df["added_date"] = df["added_date"].astype(str)
    return JSONResponse(_clean({"items": df.to_dict("records")}))


def _latest_panel():
    """Build a small panel just for today's prediction."""
    end = date.today().isoformat()
    start_train = "2024-01-01"
    panel = build_panel(start=start_train, end=end, rebalance_n=21,
                        with_target=False, verbose=False)
    if panel.empty:
        raise HTTPException(503, "No panel data — run ingestion first.")
    latest_date = panel["date"].max()
    return panel[panel["date"] == latest_date].copy(), latest_date


@app.get("/api/recommend")
def recommend(top_k: int = Query(20, ge=1, le=100)):
    try:
        bundle = load_model()
    except FileNotFoundError:
        raise HTTPException(503, "No trained model. POST /api/train first.")

    latest, latest_date = _latest_panel()
    cols = bundle["feature_cols"]
    Xte = latest[cols]  # let LightGBM handle NaN natively
    latest["pred"] = bundle["model"].predict(Xte)
    latest = latest.sort_values("pred", ascending=False).head(top_k)

    # Join with universe meta for names
    uni = get_universe_df()[["ticker", "name", "sector"]]
    out = latest.merge(uni, on="ticker", how="left")

    items = []
    for _, r in out.iterrows():
        items.append({
            "ticker": r["ticker"],
            "name": r.get("name"),
            "sector": r.get("sector"),
            "close": float(r["close"]) if pd.notna(r["close"]) else None,
            "pred_21d_return": float(r["pred"]),
            "pe": _safe(r.get("pe")),
            "pb": _safe(r.get("pb")),
            "roe_ttm": _safe(r.get("roe_ttm")),
            "mom_12_1": _safe(r.get("mom_12_1")),
            "vol_60": _safe(r.get("vol_60")),
        })
    return JSONResponse(_clean({
        "as_of_date": str(latest_date.date()) if hasattr(latest_date, "date") else str(latest_date),
        "top_k": top_k,
        "items": items,
    }))


def _safe(v):
    if v is None:
        return None
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except Exception:
        return None


@app.get("/api/analyze")
def analyze(ticker: str):
    try:
        bundle = load_model()
    except FileNotFoundError:
        raise HTTPException(503, "No trained model. Train first.")

    latest, latest_date = _latest_panel()
    row = latest[latest["ticker"] == ticker.upper()]
    if row.empty:
        raise HTTPException(404, f"{ticker} not in latest panel.")
    cols = bundle["feature_cols"]
    pred = float(bundle["model"].predict(row[cols])[0])

    uni = get_universe_df()
    meta = uni[uni["ticker"] == ticker.upper()].iloc[0].to_dict() if (
        uni["ticker"] == ticker.upper()).any() else {}

    # Build trade plan from price history
    with cursor() as con:
        px = con.execute(
            "SELECT date, high, low, close FROM prices WHERE ticker=? "
            "ORDER BY date DESC LIMIT 30",
            [ticker.upper()],
        ).df()
    px = px.sort_values("date")
    if len(px) >= 14:
        # Simple ATR(14)
        h, l, c = px["high"].values, px["low"].values, px["close"].values
        tr = np.maximum.reduce([
            h[1:] - l[1:],
            np.abs(h[1:] - c[:-1]),
            np.abs(l[1:] - c[:-1]),
        ])
        atr = float(pd.Series(tr).ewm(alpha=1/14, adjust=False).mean().iloc[-1])
    else:
        atr = float(px["close"].iloc[-1] * 0.02) if len(px) else 0.0
    close = float(px["close"].iloc[-1]) if len(px) else float(row["close"].iloc[0])
    direction = "LONG" if pred >= 0 else "SHORT"
    sign = 1 if direction == "LONG" else -1
    entry = close
    stop = close - sign * 2 * atr
    take = close + sign * 3 * atr
    risk_per_share = abs(entry - stop)
    pos_pct = min(0.25, max(0.0, 0.01 / max(risk_per_share / entry, 1e-6))) if entry else 0.0

    # Pull feature contributions (just top 5 most important features for this ticker)
    feat_dict = {c: _safe(row[c].iloc[0]) for c in cols if c in row.columns}

    return JSONResponse(_clean({
        "ticker": ticker.upper(),
        "name": meta.get("name"),
        "sector": meta.get("sector"),
        "as_of_date": str(latest_date.date()) if hasattr(latest_date, "date") else str(latest_date),
        "prediction": {
            "horizon_days": FORWARD_HORIZON,
            "expected_return": pred,
        },
        "fundamentals": {k: _safe(row[k].iloc[0]) for k in
                         ["pe", "pb", "ps", "ev_to_revenue", "fcf_yield",
                          "roa_ttm", "roe_ttm", "op_margin", "gross_margin",
                          "debt_to_equity", "current_ratio",
                          "revenue_growth_yoy", "earnings_growth_yoy",
                          "log_market_cap"] if k in row.columns},
        "technical": {k: _safe(row[k].iloc[0]) for k in
                      ["mom_1m", "mom_3m", "mom_6m", "mom_12_1", "mom_12m",
                       "vol_20", "vol_60", "rsi_14", "macd_hist",
                       "px_to_sma50", "px_to_sma200", "dd_252"] if k in row.columns},
        "trade_plan": {
            "direction": direction,
            "entry": entry, "stop_loss": stop, "take_profit": take,
            "atr14": atr, "position_size_pct": pos_pct,
            "rr_ratio": 1.5, "risk_per_trade_pct": 0.01,
        },
    }))


@app.get("/api/prices")
def prices(ticker: str, start: Optional[str] = None, end: Optional[str] = None):
    where = ["ticker = ?"]
    args = [ticker.upper()]
    if start:
        where.append("date >= ?"); args.append(start)
    if end:
        where.append("date <= ?"); args.append(end)
    q = f"SELECT date,open,high,low,close,adj_close,volume FROM prices WHERE {' AND '.join(where)} ORDER BY date"
    with cursor() as con:
        df = con.execute(q, args).df()
    candles = [{
        "date": str(r["date"]),
        "open": float(r["open"]), "high": float(r["high"]),
        "low": float(r["low"]), "close": float(r["close"]),
        "adj_close": float(r["adj_close"]), "volume": float(r["volume"]),
    } for _, r in df.iterrows()]
    return JSONResponse(_clean({"ticker": ticker.upper(), "candles": candles}))


class BacktestRequest(BaseModel):
    start: str = "2018-01-01"
    end: Optional[str] = None
    train_start: str = "2014-01-01"
    rebalance_n: int = 21
    top_k: int = 20
    cost_bps: float = COST_BPS
    slippage_bps: float = SLIPPAGE_BPS


class BacktestV3Request(BacktestRequest):
    sector_cap: float = 0.30          # tuned default
    drawdown_brake: float = -0.10     # tuned default
    use_rank_target: bool = True
    feature_suffix: str = "_sn"


@app.post("/api/backtest")
def backtest(req: BacktestRequest):
    """Run v2 backtest (regression target, raw features). Use /api/backtest_v3 for Phase 2."""
    panel_path = MODEL_DIR / "feature_panel.parquet"
    panel = pd.read_parquet(panel_path) if panel_path.exists() else None
    params = WFParams(
        start=req.start, end=req.end, train_start=req.train_start,
        rebalance_n=req.rebalance_n, top_k=req.top_k,
        cost_bps=req.cost_bps, slippage_bps=req.slippage_bps,
    )
    res = run_walkforward(params, panel=panel, verbose=False)
    if "error" in res:
        raise HTTPException(400, res["error"])
    return JSONResponse(_clean({
        "metrics": res["metrics"],
        "params": res["params"],
        "equity_curve": [
            {"date": str(d.date() if hasattr(d, "date") else d),
             "equity": float(v),
             "benchmark": float(res["benchmark_curve"].get(d, 1.0))}
            for d, v in res["equity_curve"].items()
        ],
        "ic_history": res["ic_history"][-24:],
        "holdings": res["holdings"][-12:],
    }))


@app.post("/api/backtest_v3")
def backtest_v3(req: BacktestV3Request):
    """Phase 2 backtest: rank target + sector-neutral features + sector cap + DD brake."""
    panel_path = MODEL_DIR / "feature_panel_v3.parquet"
    panel = pd.read_parquet(panel_path) if panel_path.exists() else None
    params = WFv3Params(
        start=req.start, end=req.end, train_start=req.train_start,
        rebalance_n=req.rebalance_n, top_k=req.top_k,
        cost_bps=req.cost_bps, slippage_bps=req.slippage_bps,
        sector_cap=req.sector_cap, drawdown_brake=req.drawdown_brake,
        use_rank_target=req.use_rank_target, feature_suffix=req.feature_suffix,
    )
    res = run_wf_v3(params, panel=panel, verbose=False)
    if "error" in res:
        raise HTTPException(400, res["error"])
    return JSONResponse(_clean({
        "metrics": res["metrics"],
        "params": res["params"],
        "equity_curve": [
            {"date": str(d.date() if hasattr(d, "date") else d),
             "equity": float(v),
             "benchmark": float(res["benchmark_curve"].get(d, 1.0))}
            for d, v in res["equity_curve"].items()
        ],
        "ic_history": res["ic_history"][-24:],
        "holdings": res["holdings"][-12:],
    }))


@app.get("/api/model/info")
def model_info():
    fi_path = MODEL_DIR / "feature_importance.csv"
    ic_path = MODEL_DIR / "oof_ic_by_date.csv"
    info = {}
    try:
        bundle = load_model()
        info["oof_ic_mean"] = bundle.get("oof_ic_mean")
        info["fold_metrics"] = bundle.get("fold_metrics", [])
        info["n_features"] = len(bundle.get("feature_cols", []))
    except FileNotFoundError:
        info["error"] = "No trained model yet."
    if fi_path.exists():
        fi = pd.read_csv(fi_path)
        info["feature_importance"] = fi.head(20).to_dict("records")
    if ic_path.exists():
        ic = pd.read_csv(ic_path)
        ic.columns = ["date", "ic"]
        info["ic_by_date"] = ic.tail(80).to_dict("records")
    return JSONResponse(_clean(info))


_train_status = {"running": False, "result": None, "error": None}


def _train_job():
    try:
        _train_status["running"] = True
        from app.features.pipeline import ALL_FEATURES, build_panel
        from app.model.lgbm import fit_lgbm, save_model
        panel = build_panel(start="2014-01-01", rebalance_n=21, verbose=False)
        panel.to_parquet(MODEL_DIR / "feature_panel.parquet", index=False)
        feat = [c + "_rk" for c in ALL_FEATURES if (c + "_rk") in panel.columns]
        if not feat:
            feat = [c for c in ALL_FEATURES if c in panel.columns]
        res = fit_lgbm(panel, feat, n_splits=5)
        save_model(res)
        _train_status["result"] = {
            "oof_ic_mean": res["oof_ic_mean"],
            "oof_ic_std": res["oof_ic_std"],
            "fold_metrics": res["fold_metrics"],
            "n_features": len(feat),
            "n_rows": int(len(panel)),
        }
    except Exception as e:
        _train_status["error"] = str(e)
    finally:
        _train_status["running"] = False


@app.post("/api/train")
def train(bg: BackgroundTasks):
    if _train_status["running"]:
        return {"status": "already_running"}
    _train_status["error"] = None
    _train_status["result"] = None
    bg.add_task(_train_job)
    return {"status": "started"}


@app.get("/api/train/status")
def train_status():
    return JSONResponse(_clean(_train_status))


# Static
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    @app.get("/")
    def index():
        return FileResponse(str(WEB_DIR / "index.html"))
