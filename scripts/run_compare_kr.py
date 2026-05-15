"""Run V2 (no gate) + V3a (higher-TF gate) + V3b (Triple Screen) on 30 KR
candidates and write a unified comparison report including V0 (the original
monthly_10ma report).

V0 = simple monthly_10ma strategy (책 그대로 — already in
     models_store/screen_backtest_kr_20260515_0753.{md,json,csv})
V1 = advanced 4-tier, no gating, no params tuning  (already saved)
V2 = advanced 4-tier with tuned thresholds + 240MA gate
V3a = V2 + higher-TF gate (daily gated by weekly+monthly uptrend,
      weekly gated by monthly uptrend)
V3b = Triple Screen (daily bar execution, ENTER needs all 3 TF agree)
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd

from app.book.analyzer import load_ticker_data
from app.book.backtest_advanced import (
    backtest_advanced_all_timeframes, backtest_triple_screen,
)

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


SOURCE_CSV = Path("models_store/screen_backtest_kr_20260515_0753.csv")
V1_JSON = Path("models_store/screen_backtest_advanced_kr_20260515_090928.json")
V2_JSON = Path("models_store/screen_backtest_advanced_kr_20260515_100637.json")


def _load_csv_v0() -> dict:
    out = {}
    with open(SOURCE_CSV, encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            out[row["ticker"]] = {
                "n": int(float(row["bt_n_trades"])),
                "win": float(row["bt_win_rate"]),
                "total": float(row["bt_total_return"]),
                "bh": float(row["bt_buy_and_hold"]),
                "score": float(row["book_score"]),
                "top_pattern": row["top_pattern"],
            }
    return out


def _load_prior_run(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    out = {}
    for r in data.get("results", []):
        out[r["ticker"]] = r
    return out


def _summarize_tf(results: dict, tf: str) -> dict:
    """Aggregate per-ticker entries for a given timeframe key."""
    rows = [r for r in results.values()
            if r.get(f"{tf}_n", 0) > 0]
    if not rows:
        return {"n_tickers_traded": 0}
    avg_cagr = sum(r[f"{tf}_cagr"] for r in rows) / len(rows)
    avg_bh = sum(r[f"{tf}_bh_cagr"] for r in rows) / len(rows)
    avg_alpha = sum(r[f"{tf}_alpha"] for r in rows) / len(rows)
    avg_win = sum(r[f"{tf}_win"] for r in rows) / len(rows)
    n_beat = sum(1 for r in rows if r[f"{tf}_alpha"] > 0)
    return {
        "n_tickers_traded": len(rows),
        "avg_cagr": avg_cagr, "avg_bh": avg_bh,
        "avg_alpha": avg_alpha, "avg_win": avg_win,
        "n_beat_bh": n_beat,
    }


def run_v(daily_df: pd.DataFrame, ticker: str, mode: str) -> dict:
    """Run one variant. mode='V3a' (higher-TF gate) | 'V3b' (Triple Screen)."""
    if mode == "V3a":
        res = backtest_advanced_all_timeframes(daily_df, ticker,
                                                use_higher_tf_gate=True)
    elif mode == "V3b":
        # Triple Screen runs only on daily; map to {'triple': result}
        r = backtest_triple_screen(daily_df, ticker)
        return {"triple": r}
    else:
        res = backtest_advanced_all_timeframes(daily_df, ticker,
                                                use_higher_tf_gate=False)
    return res


def main() -> int:
    v0_csv = _load_csv_v0()
    v1 = _load_prior_run(V1_JSON)
    v2 = _load_prior_run(V2_JSON)

    tickers = list(v0_csv.keys())
    print(f"[compare-kr] {len(tickers)} 종목, V3a + V3b 실행…")

    v3a_rows: dict = {}
    v3b_rows: dict = {}
    for i, tk in enumerate(tickers, 1):
        try:
            df = load_ticker_data(tk, years=15)
            if df is None or df.empty or len(df) < 300:
                print(f"  [{i}/{len(tickers)}] {tk:<12} skip (no data)")
                continue
            # V3a
            res_a = run_v(df, tk, "V3a")
            row_a = {"ticker": tk}
            for tf, r in res_a.items():
                s = r["summary"] or {}
                row_a[f"{tf}_n"] = s.get("n_trades", 0)
                row_a[f"{tf}_win"] = s.get("win_rate_pct", 0)
                row_a[f"{tf}_cagr"] = s.get("cagr_pct", 0)
                row_a[f"{tf}_bh_cagr"] = s.get("buy_and_hold_cagr", 0)
                row_a[f"{tf}_alpha"] = s.get("alpha_cagr_pct", 0)
            v3a_rows[tk] = row_a

            # V3b
            res_b = run_v(df, tk, "V3b")
            r = res_b["triple"]
            s = r["summary"] or {}
            v3b_rows[tk] = {
                "ticker": tk,
                "triple_n": s.get("n_trades", 0),
                "triple_win": s.get("win_rate_pct", 0),
                "triple_cagr": s.get("cagr_pct", 0),
                "triple_bh_cagr": s.get("buy_and_hold_cagr", 0),
                "triple_alpha": s.get("alpha_cagr_pct", 0),
                "triple_pyramid": s.get("n_pyramid_adds", 0),
                "triple_scaleout": s.get("n_scale_outs", 0),
                "triple_total": s.get("total_compound_pct", 0),
            }
            print(f"  [{i}/{len(tickers)}] {tk:<12} "
                  f"V3a-d {row_a['daily_n']}/{row_a['daily_alpha']:+.1f}% "
                  f"V3b {v3b_rows[tk]['triple_n']}/{v3b_rows[tk]['triple_alpha']:+.1f}%")
        except Exception as e:
            print(f"  [{i}/{len(tickers)}] {tk:<12} ERR: {e}")

    # ---- write comparison report ----
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path("models_store")
    out_dir.mkdir(exist_ok=True)
    stem = f"compare_kr_{ts}"

    # JSON: full
    with open(out_dir / f"{stem}.json", "w", encoding="utf-8") as f:
        json.dump({
            "generated": ts,
            "v0": v0_csv,
            "v1": v1,
            "v2": v2,
            "v3a": v3a_rows,
            "v3b": v3b_rows,
        }, f, ensure_ascii=False, indent=2, default=str)

    # Aggregates
    def v0_agg():
        rows = list(v0_csv.values())
        avg_total = sum(r["total"] for r in rows) / len(rows)
        avg_bh = sum(r["bh"] for r in rows) / len(rows)
        avg_win = sum(r["win"] for r in rows) / len(rows)
        n_beat = sum(1 for r in rows if r["total"] > r["bh"])
        return {"n": len(rows), "avg_total": avg_total, "avg_bh": avg_bh,
                "avg_win": avg_win, "n_beat": n_beat}

    v0a = v0_agg()
    v1_d = _summarize_tf(v1, "daily")
    v1_w = _summarize_tf(v1, "weekly")
    v1_m = _summarize_tf(v1, "monthly")
    v2_d = _summarize_tf(v2, "daily")
    v2_w = _summarize_tf(v2, "weekly")
    v2_m = _summarize_tf(v2, "monthly")
    v3a_d = _summarize_tf(v3a_rows, "daily")
    v3a_w = _summarize_tf(v3a_rows, "weekly")
    v3a_m = _summarize_tf(v3a_rows, "monthly")
    v3b_s = _summarize_tf(v3b_rows, "triple")

    md = [
        "# KR 30종목 백테스트 버전 비교",
        "",
        f"- 생성: {ts}",
        f"- 종목 수: **{len(tickers)}**",
        "",
        "## 버전 정의",
        "",
        "| 버전 | 설명 |",
        "|---|---|",
        "| **V0** | 책 그대로 (monthly_10ma 단일 룰, 4단계 없음) |",
        "| **V1** | Advanced 4-tier (ENTER/PYRAMID/WARN/EXIT), 튜닝 없음 |",
        "| **V2** | V1 + 시간프레임별 임계값 튜닝 + 240MA gate + WARN 강화 |",
        "| **V3a** | V2 + 상위 TF 게이트 (일봉←주봉/월봉, 주봉←월봉) |",
        "| **V3b** | Triple Screen (일봉 단위 매매, 3 TF 동시 합의 필요) |",
        "",
        "## 평균 알파 비교 (CAGR 기준, 거래발생 종목 평균)",
        "",
        "| 버전 | 거래종목 | 평균 CAGR | 평균 B&H CAGR | **알파** | B&H 초과 | 승률 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    # V0
    v0_alpha = v0a["avg_total"] - v0a["avg_bh"]
    md.append(
        f"| **V0** (monthly_10ma) | {v0a['n']}/30 | "
        f"총수익 {v0a['avg_total']:+.1f}% | "
        f"B&H {v0a['avg_bh']:+.1f}% | "
        f"**{v0_alpha:+.1f}%p (총수익)** | "
        f"{v0a['n_beat']}/30 | "
        f"{v0a['avg_win']:.1f}% |"
    )

    def _row(label, agg):
        if agg.get("n_tickers_traded", 0) == 0:
            return f"| {label} | 0/30 | — | — | — | — | — |"
        return (
            f"| {label} | {agg['n_tickers_traded']}/30 | "
            f"{agg['avg_cagr']:+.2f}% | {agg['avg_bh']:+.2f}% | "
            f"**{agg['avg_alpha']:+.2f}%** | "
            f"{agg['n_beat_bh']}/{agg['n_tickers_traded']} | "
            f"{agg['avg_win']:.1f}% |"
        )

    md.append(_row("**V1** daily", v1_d))
    md.append(_row("**V1** weekly", v1_w))
    md.append(_row("**V1** monthly", v1_m))
    md.append(_row("**V2** daily", v2_d))
    md.append(_row("**V2** weekly", v2_w))
    md.append(_row("**V2** monthly", v2_m))
    md.append(_row("**V3a** daily", v3a_d))
    md.append(_row("**V3a** weekly", v3a_w))
    md.append(_row("**V3a** monthly", v3a_m))
    md.append(_row("**V3b** triple-screen", v3b_s))

    # Per-ticker comparison table (alpha only)
    md.append("\n## 종목별 알파 (CAGR α) — daily 기준")
    md.append("")
    md.append("| Ticker | V1 d-α | V2 d-α | V3a d-α | V3b α |")
    md.append("|---|---:|---:|---:|---:|")
    for tk in tickers:
        v1r = v1.get(tk, {})
        v2r = v2.get(tk, {})
        v3ar = v3a_rows.get(tk, {})
        v3br = v3b_rows.get(tk, {})
        md.append(
            f"| **{tk}** | "
            f"{v1r.get('daily_alpha', 0):+.1f}% | "
            f"{v2r.get('daily_alpha', 0):+.1f}% | "
            f"{v3ar.get('daily_alpha', 0):+.1f}% | "
            f"{v3br.get('triple_alpha', 0):+.1f}% |"
        )

    md.append("\n## V3b Triple Screen — 상세")
    md.append("")
    md.append("| Ticker | 거래 | 승률 | 추매 | 분할매도 | 누적 | CAGR | B&H | α |")
    md.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in sorted(v3b_rows.values(), key=lambda x: -x.get("triple_alpha", 0)):
        if r["triple_n"] == 0:
            continue
        md.append(
            f"| **{r['ticker']}** | {r['triple_n']} | "
            f"{r['triple_win']:.0f}% | {r['triple_pyramid']} | "
            f"{r['triple_scaleout']} | {r['triple_total']:+.1f}% | "
            f"{r['triple_cagr']:+.2f}% | {r['triple_bh_cagr']:+.2f}% | "
            f"**{r['triple_alpha']:+.2f}%** |"
        )

    with open(out_dir / f"{stem}.md", "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")

    print(f"\n리포트 저장: {out_dir / stem}.md / .json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
