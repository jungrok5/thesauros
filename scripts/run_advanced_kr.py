"""Run advanced 4-tier backtest on the 30 KR candidates from the 0753 report.

Reads ticker list from models_store/screen_backtest_kr_20260515_0753.csv,
runs backtest_advanced_all_timeframes on each, writes a consolidated report
to models_store/screen_backtest_advanced_kr_<ts>.{md,json,csv}.
"""
from __future__ import annotations

import csv
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

# Allow running as `python scripts/run_advanced_kr.py` from project root
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.book.analyzer import load_ticker_data
from app.book.backtest_advanced import backtest_advanced_all_timeframes

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


SOURCE_CSV = Path("models_store/screen_backtest_kr_20260515_0753.csv")


def main() -> int:
    if not SOURCE_CSV.exists():
        print(f"Missing {SOURCE_CSV}", file=sys.stderr)
        return 1

    tickers = []
    with open(SOURCE_CSV, encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            tickers.append({
                "ticker": row["ticker"],
                "score": float(row.get("book_score") or 0),
                "top_pattern": row.get("top_pattern", ""),
                "top_pattern_tf": row.get("top_pattern_tf", ""),
            })

    print(f"[advanced-kr] {len(tickers)} 종목 백테스트 시작.")
    all_results = []
    for i, row in enumerate(tickers, 1):
        tk = row["ticker"]
        try:
            df = load_ticker_data(tk, years=15)
            if df is None or df.empty or len(df) < 300:
                print(f"  [{i}/{len(tickers)}] {tk:<12} — 데이터 부족, skip")
                continue
            res = backtest_advanced_all_timeframes(df, tk)
            entry = {"ticker": tk, "score": row["score"],
                     "top_pattern": row["top_pattern"],
                     "top_pattern_tf": row["top_pattern_tf"]}
            for tf, r in res.items():
                s = r["summary"] or {}
                entry[f"{tf}_n"] = s.get("n_trades", 0)
                entry[f"{tf}_win"] = s.get("win_rate_pct", 0)
                entry[f"{tf}_cagr"] = s.get("cagr_pct", 0)
                entry[f"{tf}_bh_cagr"] = s.get("buy_and_hold_cagr", 0)
                entry[f"{tf}_alpha"] = s.get("alpha_cagr_pct", 0)
                entry[f"{tf}_pyramid"] = s.get("n_pyramid_adds", 0)
                entry[f"{tf}_scaleout"] = s.get("n_scale_outs", 0)
                entry[f"{tf}_total"] = s.get("total_compound_pct", 0)
                entry[f"{tf}_trades"] = [t.to_dict() for t in r["trades"]]
            all_results.append(entry)
            best = max(
                (entry.get(f"{tf}_alpha", -999) for tf in ["daily", "weekly", "monthly"]),
                default=0,
            )
            print(f"  [{i}/{len(tickers)}] {tk:<12} "
                  f"d:{entry['daily_n']}/{entry['daily_alpha']:+.1f}% "
                  f"w:{entry['weekly_n']}/{entry['weekly_alpha']:+.1f}% "
                  f"m:{entry['monthly_n']}/{entry['monthly_alpha']:+.1f}%  "
                  f"best α {best:+.1f}%")
        except Exception as e:
            print(f"  [{i}/{len(tickers)}] {tk:<12} — ERR: {e}")
            traceback.print_exc()

    # Write outputs
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = f"screen_backtest_advanced_kr_{ts}"
    out_dir = Path("models_store")
    out_dir.mkdir(exist_ok=True)

    # JSON (full)
    with open(out_dir / f"{stem}.json", "w", encoding="utf-8") as f:
        json.dump({"generated": ts, "n": len(all_results),
                   "results": all_results},
                  f, ensure_ascii=False, indent=2, default=str)

    # CSV (summary)
    if all_results:
        keys = [k for k in all_results[0].keys() if not k.endswith("_trades")]
        with open(out_dir / f"{stem}.csv", "w", encoding="utf-8",
                  newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            for row in all_results:
                w.writerow({k: row.get(k, "") for k in keys})

    # Markdown
    md = [
        "# KR Advanced 4-tier Backtest",
        "",
        f"- 생성: {ts}",
        f"- 종목 수: **{len(all_results)}**",
        "- 엔진: `backtest_advanced` (ENTER→25% / PYRAMID→+25% / WARN→25%분할매도 / EXIT→전량)",
        "- 시간프레임: daily / weekly / monthly 각각 별도 실행",
        "",
        "## 요약 (시간프레임별)",
        "",
    ]
    for tf in ["daily", "weekly", "monthly"]:
        winners = [r for r in all_results if r.get(f"{tf}_n", 0) > 0]
        if not winners:
            md.append(f"### {tf.upper()}\n\n- 거래 발생 종목 없음.\n")
            continue
        avg_alpha = sum(r[f"{tf}_alpha"] for r in winners) / len(winners)
        n_beat = sum(1 for r in winners if r[f"{tf}_alpha"] > 0)
        avg_cagr = sum(r[f"{tf}_cagr"] for r in winners) / len(winners)
        avg_bh = sum(r[f"{tf}_bh_cagr"] for r in winners) / len(winners)
        avg_win = sum(r[f"{tf}_win"] for r in winners) / len(winners)
        md.append(f"### {tf.upper()}")
        md.append("")
        md.append(f"- 거래 발생 종목: **{len(winners)}/{len(all_results)}**")
        md.append(f"- 평균 CAGR: **{avg_cagr:+.2f}%**  /  "
                  f"평균 B&H CAGR: **{avg_bh:+.2f}%**")
        md.append(f"- 평균 α (CAGR): **{avg_alpha:+.2f}%**  /  "
                  f"B&H 초과 종목: **{n_beat}/{len(winners)}** "
                  f"({n_beat/len(winners)*100:.0f}%)")
        md.append(f"- 평균 승률: **{avg_win:.1f}%**")
        md.append("")

    # Top alpha per timeframe
    md.append("## 시간프레임별 Top-10 알파 종목\n")
    for tf in ["daily", "weekly", "monthly"]:
        winners = sorted(
            [r for r in all_results if r.get(f"{tf}_n", 0) > 0],
            key=lambda r: -r[f"{tf}_alpha"],
        )[:10]
        if not winners:
            continue
        md.append(f"### {tf.upper()} (α 기준 Top 10)\n")
        md.append("| Ticker | 거래 | 승률 | 추매 | 분할매도 | 누적 | CAGR | B&H CAGR | α |")
        md.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        for r in winners:
            md.append(
                f"| **{r['ticker']}** | {r[f'{tf}_n']} | "
                f"{r[f'{tf}_win']:.0f}% | {r[f'{tf}_pyramid']} | "
                f"{r[f'{tf}_scaleout']} | {r[f'{tf}_total']:+.1f}% | "
                f"{r[f'{tf}_cagr']:+.2f}% | {r[f'{tf}_bh_cagr']:+.2f}% | "
                f"**{r[f'{tf}_alpha']:+.2f}%** |"
            )
        md.append("")

    # Per-ticker table
    md.append("## 전체 종목 결과\n")
    md.append("| Ticker | Score | 패턴 | D-n/α | W-n/α | M-n/α |")
    md.append("|---|---:|---|---:|---:|---:|")
    for r in sorted(all_results, key=lambda x: x["ticker"]):
        md.append(
            f"| **{r['ticker']}** | {r['score']:.2f} | "
            f"{r['top_pattern']} ({r['top_pattern_tf']}) | "
            f"{r['daily_n']}/{r['daily_alpha']:+.1f}% | "
            f"{r['weekly_n']}/{r['weekly_alpha']:+.1f}% | "
            f"{r['monthly_n']}/{r['monthly_alpha']:+.1f}% |"
        )

    with open(out_dir / f"{stem}.md", "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")

    print(f"\n리포트 저장: {out_dir / stem}.{{md,json,csv}}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
