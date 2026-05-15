"""V4 (book-strict) KR 30종목 백테스트 + V0~V4 통합 비교 리포트."""
from __future__ import annotations

import csv
import json
import sys
import warnings
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

warnings.filterwarnings("ignore", category=FutureWarning)

from app.book.analyzer import load_ticker_data
from app.book.backtest_advanced import backtest_advanced_all_timeframes

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


SOURCE_CSV = Path("models_store/screen_backtest_kr_20260515_0753.csv")
V1_JSON = Path("models_store/screen_backtest_advanced_kr_20260515_090928.json")
V2_JSON = Path("models_store/screen_backtest_advanced_kr_20260515_100637.json")
V3_JSON = Path("models_store/compare_kr_20260515_105305.json")


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


def _load_prior(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _summarize_tf(results: dict, tf: str) -> dict:
    rows = [r for r in results.values() if r.get(f"{tf}_n", 0) > 0]
    if not rows:
        return {"n_tickers_traded": 0}
    avg_cagr = sum(r[f"{tf}_cagr"] for r in rows) / len(rows)
    avg_bh = sum(r[f"{tf}_bh_cagr"] for r in rows) / len(rows)
    avg_alpha = sum(r[f"{tf}_alpha"] for r in rows) / len(rows)
    avg_win = sum(r[f"{tf}_win"] for r in rows) / len(rows)
    n_beat = sum(1 for r in rows if r[f"{tf}_alpha"] > 0)
    return {"n_tickers_traded": len(rows),
            "avg_cagr": avg_cagr, "avg_bh": avg_bh,
            "avg_alpha": avg_alpha, "avg_win": avg_win,
            "n_beat_bh": n_beat}


def main() -> int:
    v0 = _load_csv_v0()
    v1_full = _load_prior(V1_JSON)
    v2_full = _load_prior(V2_JSON)
    v3_full = _load_prior(V3_JSON)
    v1 = {r["ticker"]: r for r in v1_full.get("results", [])}
    v2 = {r["ticker"]: r for r in v2_full.get("results", [])}
    v3a = v3_full.get("v3a", {}) if v3_full else {}
    v3b = v3_full.get("v3b", {}) if v3_full else {}

    tickers = list(v0.keys())
    print(f"[v4-kr] {len(tickers)} 종목, V4 (book-strict) 백테스트…")

    v4_rows = {}
    for i, tk in enumerate(tickers, 1):
        try:
            df = load_ticker_data(tk, years=15)
            if df is None or df.empty or len(df) < 300:
                print(f"  [{i}/{len(tickers)}] {tk:<12} skip")
                continue
            res = backtest_advanced_all_timeframes(
                df, tk, use_higher_tf_gate=True, book_strict=True,
            )
            row = {"ticker": tk}
            for tf, r in res.items():
                s = r["summary"] or {}
                row[f"{tf}_n"] = s.get("n_trades", 0)
                row[f"{tf}_win"] = s.get("win_rate_pct", 0)
                row[f"{tf}_cagr"] = s.get("cagr_pct", 0)
                row[f"{tf}_bh_cagr"] = s.get("buy_and_hold_cagr", 0)
                row[f"{tf}_alpha"] = s.get("alpha_cagr_pct", 0)
                row[f"{tf}_pyramid"] = s.get("n_pyramid_adds", 0)
                row[f"{tf}_total"] = s.get("total_compound_pct", 0)
            v4_rows[tk] = row
            print(f"  [{i}/{len(tickers)}] {tk:<12} "
                  f"d:{row['daily_n']}/{row['daily_win']:.0f}%/{row['daily_alpha']:+.1f}% "
                  f"w:{row['weekly_n']}/{row['weekly_alpha']:+.1f}% "
                  f"m:{row['monthly_n']}/{row['monthly_alpha']:+.1f}%")
        except Exception as e:
            import traceback
            print(f"  [{i}/{len(tickers)}] {tk:<12} ERR: {e}")
            traceback.print_exc()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path("models_store")
    out_dir.mkdir(exist_ok=True)
    stem = f"v4_kr_{ts}"

    with open(out_dir / f"{stem}.json", "w", encoding="utf-8") as f:
        json.dump({"generated": ts, "results": v4_rows},
                  f, ensure_ascii=False, indent=2, default=str)

    def v0_agg():
        rs = list(v0.values())
        return {
            "n": len(rs),
            "avg_total": sum(r["total"] for r in rs) / len(rs),
            "avg_bh": sum(r["bh"] for r in rs) / len(rs),
            "avg_win": sum(r["win"] for r in rs) / len(rs),
            "n_beat": sum(1 for r in rs if r["total"] > r["bh"]),
        }

    v0a = v0_agg()
    v1_d = _summarize_tf(v1, "daily"); v1_w = _summarize_tf(v1, "weekly"); v1_m = _summarize_tf(v1, "monthly")
    v2_d = _summarize_tf(v2, "daily"); v2_w = _summarize_tf(v2, "weekly"); v2_m = _summarize_tf(v2, "monthly")
    v3a_d = _summarize_tf(v3a, "daily"); v3a_w = _summarize_tf(v3a, "weekly"); v3a_m = _summarize_tf(v3a, "monthly")
    v3b_t = _summarize_tf(v3b, "triple")
    v4_d = _summarize_tf(v4_rows, "daily")
    v4_w = _summarize_tf(v4_rows, "weekly")
    v4_m = _summarize_tf(v4_rows, "monthly")

    def _row(label, agg, *, total_metric=False):
        if total_metric:
            v0_alpha = agg["avg_total"] - agg["avg_bh"]
            return (
                f"| {label} | {agg['n']}/30 | 총수익 {agg['avg_total']:+.1f}% "
                f"| B&H {agg['avg_bh']:+.1f}% | **{v0_alpha:+.1f}%p** "
                f"| {agg['n_beat']}/30 | {agg['avg_win']:.1f}% |"
            )
        if agg.get("n_tickers_traded", 0) == 0:
            return f"| {label} | 0/30 | — | — | — | — | — |"
        return (
            f"| {label} | {agg['n_tickers_traded']}/30 | "
            f"{agg['avg_cagr']:+.2f}% | {agg['avg_bh']:+.2f}% | "
            f"**{agg['avg_alpha']:+.2f}%** | "
            f"{agg['n_beat_bh']}/{agg['n_tickers_traded']} | "
            f"{agg['avg_win']:.1f}% |"
        )

    md = [
        "# KR 30종목 — 책 충실도 5단계 비교 (V0 ~ V4)",
        "",
        f"- 생성: {ts}",
        f"- 종목 수: **{len(tickers)}**",
        "",
        "## 버전 정의 (책 충실도 ↑)",
        "",
        "| 버전 | 새 기능 |",
        "|---|---|",
        "| **V0** | 책 그대로 monthly_10ma 단일 룰 |",
        "| **V1** | 4단계 (ENTER/PYRAMID/WARN/EXIT) + 책 패턴 14종 |",
        "| **V2** | V1 + 임계값 튜닝 + 240MA gate + WARN 강화 |",
        "| **V3a** | V2 + 상위 TF 게이트 (일봉←주봉/월봉) |",
        "| **V3b** | Triple Screen (3 TF 동시 합의) |",
        "| **V4** | V3 + 책 강화 11종: 쎕기수렴/눌림목/5,3,3-1/마덿값/박스권금지/역배열금지/simple_book_exit/금요일만매매 |",
        "",
        "## 평균 알파 비교",
        "",
        "| 버전 | 거래종목 | 평균 CAGR | B&H CAGR | 알파 | B&H 초과 | 승률 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    md.append(_row("**V0** monthly_10ma", v0a, total_metric=True))
    md.append(_row("**V1** daily", v1_d))
    md.append(_row("**V1** weekly", v1_w))
    md.append(_row("**V1** monthly", v1_m))
    md.append(_row("**V2** daily", v2_d))
    md.append(_row("**V2** weekly", v2_w))
    md.append(_row("**V2** monthly", v2_m))
    md.append(_row("**V3a** daily", v3a_d))
    md.append(_row("**V3a** weekly", v3a_w))
    md.append(_row("**V3a** monthly", v3a_m))
    md.append(_row("**V3b** triple", v3b_t))
    md.append(_row("**V4** daily", v4_d))
    md.append(_row("**V4** weekly", v4_w))
    md.append(_row("**V4** monthly", v4_m))

    md.append("\n## V4 Top-10 알파 (daily 기준)\n")
    md.append("| Ticker | 거래 | 승률 | 추매 | 누적 | CAGR | B&H | α |")
    md.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for r in sorted([r for r in v4_rows.values() if r["daily_n"] > 0],
                     key=lambda x: -x["daily_alpha"])[:10]:
        md.append(
            f"| **{r['ticker']}** | {r['daily_n']} | "
            f"{r['daily_win']:.0f}% | {r['daily_pyramid']} | "
            f"{r['daily_total']:+.1f}% | {r['daily_cagr']:+.2f}% | "
            f"{r['daily_bh_cagr']:+.2f}% | **{r['daily_alpha']:+.2f}%** |"
        )

    md.append("\n## 종목별 alpha 진화 (daily, V1→V4)\n")
    md.append("| Ticker | V1 α | V2 α | V3a α | V4 α | V4 거래수 | V4 승률 |")
    md.append("|---|---:|---:|---:|---:|---:|---:|")
    for tk in tickers:
        v1r = v1.get(tk, {})
        v2r = v2.get(tk, {})
        v3ar = v3a.get(tk, {})
        v4r = v4_rows.get(tk, {})
        md.append(
            f"| **{tk}** | "
            f"{v1r.get('daily_alpha', 0):+.1f}% | "
            f"{v2r.get('daily_alpha', 0):+.1f}% | "
            f"{v3ar.get('daily_alpha', 0):+.1f}% | "
            f"**{v4r.get('daily_alpha', 0):+.1f}%** | "
            f"{v4r.get('daily_n', 0)} | "
            f"{v4r.get('daily_win', 0):.0f}% |"
        )

    with open(out_dir / f"{stem}.md", "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")

    print(f"\n리포트: {out_dir / stem}.md / .json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
