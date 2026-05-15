"""책 V4 포트폴리오 백테스트 — US S&P500 universe, ML V2/V3 와 동일 조건."""
from __future__ import annotations

import json
import sys
import warnings
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

warnings.filterwarnings("ignore")

import pandas as pd

from app.book.backtest_portfolio import (
    backtest_portfolio_v4, PortfolioParams,
)
from app.data.pit_db import cursor

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def main() -> int:
    # Universe: ML V3 가 쓴 S&P500 종목 = US tickers (KS/KQ 제외)
    with cursor() as con:
        tickers = [
            r[0] for r in con.execute(
                "SELECT DISTINCT ticker FROM prices "
                "WHERE ticker NOT LIKE '%.KS' AND ticker NOT LIKE '%.KQ' "
                "ORDER BY ticker"
            ).fetchall()
        ]
    print(f"[port-V4-us] universe: {len(tickers)} US tickers")

    params = PortfolioParams(
        start=pd.Timestamp("2020-01-02"),
        end=pd.Timestamp("2024-12-31"),
        max_holdings=30,
        decision_freq="weekly",
        cost_bps=10.0,
        book_strict=True,
    )

    result = backtest_portfolio_v4(tickers, params=params, verbose=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path("models_store")
    out_dir.mkdir(exist_ok=True)
    stem = f"port_v4_us_{ts}"

    # Save equity curves + metrics
    payload = {
        "generated": ts,
        "metrics": result["metrics"],
        "params": result["params"],
        "n_decisions": result["n_decisions"],
        "n_tickers_in_universe": result["n_tickers_in_universe"],
        "equity": [
            {"date": str(d.date()), "equity": float(eq),
             "benchmark": float(b)}
            for (d, eq), (_, b) in zip(
                result["equity_curve"].items(),
                result["benchmark_curve"].items()
            )
        ],
    }
    with open(out_dir / f"{stem}.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)

    # Compare against ML
    cmp_path = Path("models_store/comparison_v2_vs_v3.json")
    ml_v2 = ml_v3 = None
    if cmp_path.exists():
        with open(cmp_path, encoding="utf-8") as f:
            d = json.load(f)
        ml_v2 = d.get("v2", {}).get("metrics")
        ml_v3 = d.get("v3", {}).get("metrics")

    md = [
        "# 책 V4 포트폴리오 vs ML V2/V3 (공정 비교)",
        "",
        f"- 생성: {ts}",
        f"- Universe: **{result['n_tickers_in_universe']} US S&P500 tickers**",
        f"- 기간: 2020-01-02 ~ 2024-12-31",
        f"- 책 결정 주기: 주봉 (금요일 종가)",
        f"- 최대 보유 종목: 30 (ML top_k 와 동일)",
        f"- 거래비용: 10 bps",
        f"- 벤치마크: equal-weight S&P500 buy-and-hold",
        f"- 책 결정 횟수: **{result['n_decisions']}**",
        "",
        "## 동일 조건 결과 비교",
        "",
        "| 지표 | ML V2 (factor zoo) | ML V3 (P1~P7) | **책 V4 (4-tier + 11 gates)** |",
        "|---|---:|---:|---:|",
    ]
    m = result["metrics"]

    def _fmt(v2_k, v3_k, v4_v, pct=True):
        v2v = ml_v2.get(v2_k, 0) if ml_v2 else 0
        v3v = ml_v3.get(v3_k, 0) if ml_v3 else 0
        scale = 100 if pct else 1
        unit = "%" if pct else ""
        return (f"| {v2v*scale:+.2f}{unit} | {v3v*scale:+.2f}{unit} | "
                f"**{v4_v*scale:+.2f}{unit}** |")

    md.append("| CAGR | " + _fmt("cagr", "cagr", m["cagr"]))
    md.append("| B&H CAGR | " + _fmt("bench_cagr", "bench_cagr", m["bench_cagr"]))
    md.append("| **알파 (CAGR α)** | " + _fmt("alpha", "alpha", m["alpha"]))
    md.append("| 연 변동성 | " + _fmt("vol_annual", "vol_annual", m["vol_annual"]))
    md.append("| Sharpe | " + _fmt("sharpe", "sharpe", m["sharpe"], pct=False))
    md.append("| Info Ratio | " + _fmt("info_ratio", "info_ratio", m["info_ratio"], pct=False))
    md.append("| Max Drawdown | " + _fmt("max_drawdown", "max_drawdown", m["max_drawdown"]))
    md.append("| 일일 승률 | " + _fmt("win_rate_daily", "win_rate_daily", m["win_rate_daily"]))
    md.append("| 총수익 | " + _fmt("total_return", "total_return", m["total_return"]))
    md.append("")
    md.append("## 해석")
    md.append("")
    md.append("이번에는 **같은 universe + 같은 기간 + 포트폴리오 차원** 으로 공정 비교됨.")
    md.append("이전 KR 30종목 백테스트는 책 V0 가 미리 추린 strong-buy 만 본 것이라 책 룰이 불리했음.")

    with open(out_dir / f"{stem}.md", "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")

    print(f"\n리포트: {out_dir / stem}.md / .json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
