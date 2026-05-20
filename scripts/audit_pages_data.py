"""Cross-check each page's data against Naver mobile API."""
from __future__ import annotations

import random
import sys
import io
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
load_dotenv(_ROOT / ".env")

from app.db import get_conn  # noqa: E402

H = {"User-Agent": "Mozilla/5.0", "Referer": "https://m.stock.naver.com/"}
random.seed(42)


def naver_basic(code: str) -> dict | None:
    try:
        r = requests.get(
            f"https://m.stock.naver.com/api/stock/{code}/integration",
            headers=H, timeout=8,
        )
        if not r.ok:
            return None
        d = r.json()
        ti = {it["key"]: it["value"] for it in d.get("totalInfos", [])}
        return {
            "name": d.get("stockName"),
            "prev": ti.get("전일"),
            "vol": ti.get("거래량"),
            "mcap": ti.get("시총"),
            "per": ti.get("PER"),
            "pbr": ti.get("PBR"),
        }
    except Exception:
        return None


def main():
    print("=" * 92)
    print("[1/6] /flow-ranking — 매수 TOP 3 (외인+기관 14일 누적)")
    print("=" * 92)
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM top_flow_rankings(14, 3, 'buy')")
            for r in cur.fetchall():
                t, fs, ins, cs, days = r
                code = t.split(".")[0]
                cur2 = conn.cursor()
                cur2.execute("SELECT name FROM tickers WHERE ticker=%s", (t,))
                our_name = (cur2.fetchone() or ["?"])[0]
                cur2.close()
                nv = naver_basic(code)
                ok = "OK" if nv and nv["name"] == our_name else "MISMATCH"
                print(f"  {t:<11} 우리:{our_name:<14} Naver:{nv['name'] if nv else '?':<14} [{ok}]")
                print(f"    합 {float(cs)/1e8:.0f}억  시총={nv['mcap'] if nv else '?'}  거래량={nv['vol'] if nv else '?'}")

    print()
    print("=" * 92)
    print("[2/6] /volume-surge — TOP 2 + 랜덤 3 (총 5개)")
    print("=" * 92)
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM volume_surges(2.0, 4, 30)")
            all_surge = cur.fetchall()
            if len(all_surge) >= 5:
                picks = [all_surge[0], all_surge[1]] + random.sample(all_surge[2:], 3)
            else:
                picks = all_surge
            for r in picks:
                t = r[0]
                code = t.split(".")[0]
                ratio = float(r[3])
                close_v = int(r[4])
                pct = float(r[6])
                cur2 = conn.cursor()
                cur2.execute("SELECT name FROM tickers WHERE ticker=%s", (t,))
                our_name = (cur2.fetchone() or ["?"])[0]
                cur2.close()
                nv = naver_basic(code)
                ok = "OK" if nv and nv["name"] == our_name else "MISMATCH"
                print(f"  {t:<11} {our_name:<14} ratio={ratio:.1f}x  close={close_v:>7,}  주변동={pct:+.1f}%  [{ok}]")
                print(f"    Naver 시총={nv['mcap'] if nv else '?'}  오늘vol={nv['vol'] if nv else '?'}")

    print()
    print("=" * 92)
    print("[3/6] /screener — 6 preset 각 TOP 1")
    print("=" * 92)
    # Type-cast each arg by its function signature so the resolver
    # doesn't see ambiguous `unknown` types when we pass NULL.
    TYPE_CAST = {
        "p_per_min": "NUMERIC", "p_per_max": "NUMERIC", "p_pbr_max": "NUMERIC",
        "p_roe_min": "NUMERIC", "p_debt_ratio_max": "NUMERIC",
        "p_op_margin_min": "NUMERIC", "p_revenue_growth_min": "NUMERIC",
        "p_passes_graham": "BOOLEAN", "p_passes_buffett": "BOOLEAN",
        "p_passes_magic": "BOOLEAN", "p_passes_kang": "BOOLEAN",
        "p_action": "TEXT", "p_action_in": "TEXT[]",
        "p_book_score_min": "NUMERIC", "p_limit": "INT",
    }
    PRESETS = [
        ("book-buy",       {"p_action_in": ["STRONG_BUY", "BUY"], "p_book_score_min": 0.7, "p_roe_min": 0.05}),
        ("value-classic",  {"p_passes_graham": True, "p_passes_buffett": True}),
        ("value-deep",     {"p_per_max": 10, "p_pbr_max": 1.0, "p_debt_ratio_max": 1.0}),
        ("growth-quality", {"p_revenue_growth_min": 0.10, "p_roe_min": 0.15, "p_debt_ratio_max": 1.0, "p_pbr_max": 5, "p_per_max": 40}),
        ("high-dividend",  {"p_roe_min": 0.10, "p_debt_ratio_max": 0.50}),
        ("magic-formula",  {"p_passes_magic": True}),
    ]
    ALL_ARGS = list(TYPE_CAST.keys())
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            for name, kw in PRESETS:
                params = {**{a: None for a in ALL_ARGS}, **kw, "p_limit": 1}
                placeholders = ", ".join(
                    f"{a} => %s::{TYPE_CAST[a]}" for a in ALL_ARGS
                )
                cur.execute(
                    f"SELECT * FROM screener_results({placeholders})",
                    [params[a] for a in ALL_ARGS],
                )
                row = cur.fetchone()
                if not row:
                    print(f"  {name:<16} (no result)")
                    continue
                t, db_name, per, pbr, roe, dr, om, rg, action, score = row
                code = t.split(".")[0]
                nv = naver_basic(code)
                ok = "OK" if nv and nv["name"] == db_name else "MISMATCH"
                print(f"  {name:<16} 1위:{t:<11} {db_name:<14} "
                      f"PER={float(per or 0):.1f} PBR={float(pbr or 0):.2f} ROE={float(roe or 0)*100:.1f}% "
                      f"{action or '-':<14} score={float(score or 0):.2f} [{ok}]")
                if nv:
                    print(f"    Naver: PER={nv['per']} PBR={nv['pbr']} 시총={nv['mcap']}")

    print()
    print("=" * 92)
    print("[4/6] /dashboard — 거시 지표 5개")
    print("=" * 92)
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT macro_indicators, updated_at FROM macro_state WHERE id=1")
            row = cur.fetchone()
            if row:
                ms, ts = row
                print(f"  업데이트: {ts}")
                if ms:
                    sample_keys = ["cpi", "m2_supply", "fed_funds_rate", "dxy", "tips_breakeven_10y"]
                    for k in sample_keys:
                        v = ms.get(k)
                        if not v:
                            continue
                        print(f"  {k:<25} value={v.get('value')} state={v.get('state')} as_of={v.get('as_of')}")

    print()
    print("=" * 92)
    print("[5/6] 종목 상세 — 대형주 랜덤 3종 (시세 + 펀더 + 분석)")
    print("=" * 92)
    candidates = ["005930.KS", "000660.KS", "035420.KQ", "035720.KS", "005380.KS", "068270.KS"]
    random.shuffle(candidates)
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            for t in candidates[:3]:
                code = t.split(".")[0]
                cur.execute("SELECT name FROM tickers WHERE ticker=%s", (t,))
                our_name = (cur.fetchone() or ["?"])[0]
                cur.execute("SELECT result FROM analyze_results WHERE ticker=%s", (t,))
                ar = (cur.fetchone() or [None])[0] or {}
                cur.execute(
                    "SELECT bar_date, close FROM bars WHERE ticker=%s "
                    "AND granularity='W' ORDER BY bar_date DESC LIMIT 1", (t,))
                bar = cur.fetchone()
                cur.execute("SELECT per, pbr, roe FROM factors_eval WHERE ticker=%s", (t,))
                f = cur.fetchone()
                nv = naver_basic(code)
                ok = "OK" if nv and nv["name"] == our_name else "MISMATCH"
                print(f"  {t} {our_name} [{ok}]")
                if bar:
                    print(f"    bars W 최신: {bar[0]} close={float(bar[1])}")
                if ar:
                    print(f"    analyze: last_close={ar.get('last_close')} action={ar.get('action')} score={ar.get('book_score')}")
                if f:
                    print(f"    우리 factors: PER={float(f[0] or 0):.2f} PBR={float(f[1] or 0):.2f} ROE={float(f[2] or 0)*100:.1f}%")
                if nv:
                    print(f"    Naver:       PER={nv['per']} PBR={nv['pbr']} 시총={nv['mcap']} 전일={nv['prev']}")

    print()
    print("=" * 92)
    print("[6/6] /watchlist — DB 의 임의 사용자 watchlist 3종")
    print("=" * 92)
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT w.ticker, t.name, w.category, w.entry_price "
                "FROM watchlist w LEFT JOIN tickers t ON t.ticker = w.ticker "
                "ORDER BY w.created_at DESC LIMIT 3"
            )
            for t, name, cat, entry in cur.fetchall():
                code = t.split(".")[0]
                nv = naver_basic(code)
                ok = "OK" if nv and nv["name"] == name else "MISMATCH"
                ep = float(entry) if entry else None
                print(f"  {t} {name} ({cat}, entry={ep}) ← Naver:{nv['name'] if nv else '?'} 전일={nv['prev'] if nv else '?'} [{ok}]")


if __name__ == "__main__":
    main()
