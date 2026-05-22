"""Telegram alert worker — sends signal changes to subscribed users.

How it works (idempotent, safe to re-run):
  1. For every user with a telegram_chat_id, look at their watchlist.
  2. For each watched ticker, find active scan_results signals.
  3. Compare against `alerts` table — emit a row only if the same
     (user_id, ticker, alert_type) row isn't already present *for this
     detected_at timestamp*.
  4. Send the new alert messages to Telegram, mark sent_telegram=true.

Designed to be called from GitHub Actions cron after `scan_daily.py`,
so signals are already fresh in `scan_results`.

Alert types mapped from scan_results.signal_type:
  - action_strong_buy / action_buy → 'enter' (severity info)
  - action_sell / action_sell_short → 'exit'  (severity critical)
  - pattern_* (bullish)             → 'pyramid' if already holding
  - volume_case_9 / death_messenger → 'warn'
  - ma240_break_down                → 'exit'

Usage:
    python -m app.db.telegram_worker
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.db import get_conn   # noqa: E402
from app.db.webpush import is_available as webpush_available, send_many  # noqa: E402

log = logging.getLogger("telegram_worker")


# ---- Mapping: scan_results.signal_type → alert.alert_type, severity ----

ALERT_RULES: List[Tuple[str, str, str]] = [
    # (signal_type_prefix_or_exact, alert_type, severity)
    ("action_strong_buy",       "enter",    "info"),
    ("action_buy",              "enter",    "info"),
    ("action_sell_short",       "exit",     "critical"),
    ("action_sell",             "exit",     "critical"),
    ("volume_case_9",           "warn",     "warn"),
    ("volume_case_10",          "warn",     "warn"),
    ("pattern_death_messenger", "exit",     "critical"),
    ("ma240_break_down",        "exit",     "critical"),
    ("pattern_double_top",      "warn",     "warn"),
    ("pattern_head_and_shoulders", "warn",  "warn"),
    ("pattern_triple_top",      "warn",     "warn"),
    # bullish patterns → pyramid signal (only fires for holding category)
    ("pattern_double_bottom",   "pyramid",  "info"),
    ("pattern_inverse_head_and_shoulders", "pyramid", "info"),
    ("pattern_triple_bottom",   "pyramid",  "info"),
    ("pattern_cup_and_handle",  "pyramid",  "info"),
    ("pattern_doulbanji",       "pyramid",  "info"),
]


def classify(signal_type: str) -> Optional[Tuple[str, str]]:
    """signal_type → (alert_type, severity) or None to skip."""
    for prefix, atype, sev in ALERT_RULES:
        if signal_type == prefix or signal_type.startswith(prefix + "_"):
            return atype, sev
    return None


# ---- Telegram send ------------------------------------------------------

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def send_telegram(chat_id: str, text: str, *, token: Optional[str] = None,
                  max_retries: int = 3) -> bool:
    """Send a Telegram message with proper 429 backoff.

    Telegram's global limit is ~30 msg/sec; per-chat limit is ~1 msg/sec.
    On 429 the response includes `parameters.retry_after` (seconds). We
    respect that and retry up to `max_retries` times.
    """
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        log.error("TELEGRAM_BOT_TOKEN missing")
        return False
    url = TELEGRAM_API.format(token=token)
    for attempt in range(max_retries):
        try:
            r = requests.post(url, data={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": "true",
            }, timeout=10)
            if r.ok:
                return True
            if r.status_code == 429:
                # Telegram tells us exactly how long to wait.
                try:
                    retry_after = int(r.json().get("parameters", {}).get("retry_after", 1))
                except Exception:
                    retry_after = 2 ** attempt
                log.info("telegram 429 — sleeping %ds (attempt %d/%d)",
                         retry_after, attempt + 1, max_retries)
                time.sleep(retry_after)
                continue
            # Other non-OK (400 bad chat, 403 blocked, etc.) — don't retry.
            log.warning("telegram send failed (%s): %s",
                        r.status_code, r.text[:200])
            return False
        except Exception as e:
            log.warning("telegram send error (attempt %d/%d): %s",
                        attempt + 1, max_retries, e)
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
    return False


# ---- DB queries --------------------------------------------------------

def _users_with_alerts() -> List[Dict[str, Any]]:
    """Users with at least one delivery channel (telegram OR web-push)."""
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT u.id, u.email, u.telegram_chat_id, "
                "       EXISTS(SELECT 1 FROM push_subscriptions ps "
                "              WHERE ps.user_id = u.id) AS has_push "
                "FROM users u "
                "WHERE u.telegram_chat_id IS NOT NULL "
                "   OR EXISTS(SELECT 1 FROM push_subscriptions ps "
                "             WHERE ps.user_id = u.id)"
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def _push_subs_for(user_id: str) -> List[Dict[str, Any]]:
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT endpoint, p256dh, auth FROM push_subscriptions "
                "WHERE user_id = %s",
                (user_id,),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def _delete_push_subs(endpoints: List[str]) -> None:
    if not endpoints:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM push_subscriptions WHERE endpoint = ANY(%s)",
                (endpoints,),
            )


def _watchlist_active(user_id: str) -> List[Dict[str, Any]]:
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ticker, category, entry_price, "
                "       target_price, target_pct_from_entry, "
                "       stop_price,   stop_pct_from_entry,   "
                "       target_hit_at, stop_hit_at "
                "FROM watchlist "
                "WHERE user_id = %s AND alerts_enabled = true",
                (user_id,),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def _user_prefs(user_id: str) -> Dict[str, bool]:
    """Returns alert_preferences row as dict; missing row = all-on defaults.

    `enable_daily_top5` column still exists in the table (kept for
    backward compat) but is no longer queried — the /recommendations
    page that consumed the digest was removed in the search-only
    pivot (2026-05-19) and telegram_worker never wired a sender for it.
    """
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT enable_enter, enable_pyramid, enable_warn, "
                "enable_exit, enable_ma240_break, enable_quarter_25_break "
                "FROM alert_preferences WHERE user_id = %s",
                (user_id,),
            )
            r = cur.fetchone()
            if not r:
                return {k: True for k in (
                    "enable_enter", "enable_pyramid", "enable_warn",
                    "enable_exit", "enable_ma240_break",
                    "enable_quarter_25_break",
                )}
            keys = [d[0] for d in cur.description]
            return {k: bool(v) for k, v in zip(keys, r)}


def _latest_close(ticker: str) -> Optional[float]:
    """Latest weekly close — used to compare against target/stop levels."""
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT close FROM bars WHERE ticker = %s AND granularity = 'W' "
                "ORDER BY bar_date DESC LIMIT 1",
                (ticker,),
            )
            r = cur.fetchone()
            return float(r[0]) if r and r[0] is not None else None


def _mark_hit(user_id: str, ticker: str, column: str) -> None:
    if column not in ("target_hit_at", "stop_hit_at"):
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE watchlist SET {column} = now() "
                "WHERE user_id = %s AND ticker = %s",
                (user_id, ticker),
            )


_PREF_BY_ALERT = {
    "enter":   "enable_enter",
    "pyramid": "enable_pyramid",
    "warn":    "enable_warn",
    "exit":    "enable_exit",
    "target":  "enable_enter",          # treat 🎯 as enter-class
    "stop":    "enable_exit",           # treat 🛑 as exit-class
    "quarter_25": "enable_quarter_25_break",
    "ma240":   "enable_ma240_break",
}


def _active_signals_for(tickers: List[str]) -> List[Dict[str, Any]]:
    if not tickers:
        return []
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, ticker, signal_type, timeframe, detected_at, "
                "strength, reason, params "
                "FROM scan_results WHERE is_active = true AND ticker = ANY(%s)",
                (tickers,),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


# ── Korean labels for raw signal_type values, mirroring the TS-side
#    web-next/src/lib/signal-labels.ts so push and site use the same names.

_SIGNAL_LABELS: Dict[str, Dict[str, str]] = {
    # bullish patterns
    "pattern_double_bottom":              {"name": "쌍바닥",       "dir": "bull", "phrase": "쌍바닥 매수 반전 패턴"},
    "pattern_triple_bottom":              {"name": "삼중바닥",     "dir": "bull", "phrase": "삼중바닥 매수 반전 패턴"},
    "pattern_inverse_head_and_shoulders": {"name": "역H&S",       "dir": "bull", "phrase": "역헤드앤숄더 매수 반전 패턴"},
    "pattern_forking":                    {"name": "포킹",         "dir": "bull", "phrase": "포킹 — 상승 분기 매수"},
    "pattern_cup_with_handle":            {"name": "컵핸들",       "dir": "bull", "phrase": "컵 위드 핸들 매수 추세 지속"},
    # bearish patterns
    "pattern_double_top":                 {"name": "쌍천장",       "dir": "bear", "phrase": "쌍천장 매도 반전 패턴"},
    "pattern_triple_top":                 {"name": "삼중천장",     "dir": "bear", "phrase": "삼중천장 매도 반전 패턴"},
    "pattern_head_and_shoulders":         {"name": "H&S",         "dir": "bear", "phrase": "헤드앤숄더 매도 반전 패턴"},
    # volume cases
    "volume_case_3":  {"name": "거래량 폭증",   "dir": "bull", "phrase": "Case 3 — 바닥권 거래량 폭증 (매수 진입)"},
    "volume_case_4":  {"name": "거래량 횡보",   "dir": "neutral", "phrase": "Case 4 — 횡보권 거래량 폭증"},
    "volume_case_7":  {"name": "역배 거래량",   "dir": "bear", "phrase": "Case 7 — 상승 중 거래량 급감"},
    "volume_case_9":  {"name": "분배 거래량",   "dir": "bear", "phrase": "Case 9 — 분배 의심 거래량 (매도)"},
    "volume_case_10": {"name": "분배 거래량",   "dir": "bear", "phrase": "Case 10 — 분배"},
    "volume_case_11": {"name": "투매 거래량",   "dir": "bull", "phrase": "Case 11 — 투매 후 잔량 (바닥 신호)"},
    # actions
    "action_strong_buy":  {"name": "강한 매수",  "dir": "bull", "phrase": "다중 시간프레임 정렬 + 패턴 발현 (강한 매수)"},
    "action_buy":         {"name": "매수",       "dir": "bull", "phrase": "추세 우호 정렬 (매수)"},
    "action_sell":        {"name": "매도",       "dir": "bear", "phrase": "10MA 이탈 (매도)"},
    "action_sell_short":  {"name": "청산/인버스", "dir": "bear", "phrase": "추세 사망 (청산 또는 인버스 진입)"},
    "action_avoid":       {"name": "회피",       "dir": "bear", "phrase": "240MA 아래 — 죽은 차트 (회피)"},
}


def _signal_label(signal_type: str) -> Dict[str, str]:
    return _SIGNAL_LABELS.get(signal_type, {
        "name": signal_type, "dir": "neutral", "phrase": signal_type,
    })


def _analyze_blob(ticker: str) -> Optional[Dict[str, Any]]:
    """Pull the analyze_results.result blob for a ticker, or None."""
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT result FROM analyze_results WHERE ticker = %s",
                (ticker,),
            )
            r = cur.fetchone()
            return r[0] if r and r[0] else None


def _freshness_of(blob: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Best fresh bullish pattern (kind + runup% past breakout level).

    Mirrors web-next/src/lib/freshness.ts::pickFreshest — pattern.entry
    is unreliable for runup since the analyzer sets it to last_close on
    completion, so we use extra.neckline / rim / ma_240 / ma_value as
    the real breakout reference. Patterns without one are skipped.
    """
    patterns = (blob or {}).get("patterns") or []
    last_close = (blob or {}).get("last_close")
    if not isinstance(last_close, (int, float)) or last_close <= 0:
        return None

    def _bucket(r: float) -> int:
        if 0 <= r < 5: return 0
        if 5 <= r < 15: return 1
        if 15 <= r < 30: return 2
        if -10 <= r < 0: return 3
        if r < -10: return 4
        return 5

    best = None
    for p in patterns:
        if not p.get("completed") or p.get("direction") != "bullish":
            continue
        extra = p.get("extra") or {}
        bl = None
        for k in ("neckline", "rim", "ma_240", "ma_value"):
            v = extra.get(k)
            if isinstance(v, (int, float)) and v > 0:
                bl = v
                break
        if bl is None:
            continue
        runup = (float(last_close) / float(bl) - 1) * 100
        if best is None or _bucket(runup) < _bucket(best["runup"]):
            best = {"kind": p.get("kind", "?"), "runup": runup}
    return best


def _fresh_zone_label(runup: float) -> str:
    if runup < -10: return "🔴 무효 가능"
    if runup < 0:   return "풀백 검토"
    if runup < 5:   return "🟢 지금 진입 자리"
    if runup < 15:  return "추격 가능"
    if runup < 30:  return "일부 진입 자리 지남"
    return "⚠ 진입 자리 끝남"


def _flow_5d(ticker: str) -> Optional[Dict[str, float]]:
    """5-day sum of foreign + institution net flow. KR only — returns None
    for US (no data) so the caller can skip the corroboration line."""
    if not (ticker.endswith(".KS") or ticker.endswith(".KQ")):
        return None
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(SUM(foreign_net),0), COALESCE(SUM(institution_net),0) "
                "FROM investor_flow "
                "WHERE ticker = %s AND day >= CURRENT_DATE - INTERVAL '7 days'",
                (ticker,),
            )
            r = cur.fetchone()
            if not r:
                return None
            return {"foreign": float(r[0] or 0), "inst": float(r[1] or 0)}


def _already_alerted(user_id: str, ticker: str, alert_type: str,
                     signal_detected_at: str) -> bool:
    """Check if (user, ticker, alert_type) was alerted recently.

    Uses an absolute time window (24h) instead of `created_at >=
    signal_detected_at`. The original detected_at comparison fails
    silently when signal_detected_at is in the future (weekly bars
    set as_of to next Friday) — `created_at >= 미래` is always false,
    so dedupe is bypassed and the same alert fires every cron run.
    Bug seen 2026-05-20 — same SDI alert sent 13 times in 24h.

    24h window: matches the daily-scan cadence (5pm KST), so a real
    new signal next day still gets through, but bursty mid-day cron
    dispatches don't re-fire. signal_detected_at is retained for
    backward compat / future use but no longer participates in the
    SQL — checked covered by test_telegram_worker_dedupe.py.
    """
    _ = signal_detected_at  # kept for backward-compat signature
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM alerts WHERE user_id = %s AND ticker = %s "
                "AND alert_type = %s "
                "AND created_at >= NOW() - INTERVAL '24 hours' LIMIT 1",
                (user_id, ticker, alert_type),
            )
            return cur.fetchone() is not None


def _insert_alert(user_id: str, ticker: str, alert_type: str, message: str,
                  severity: str, sent: bool) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alerts (user_id, ticker, alert_type, message,
                                    severity, sent_telegram, sent_at)
                VALUES (%s, %s, %s, %s, %s, %s, CASE WHEN %s THEN now() ELSE NULL END)
                """,
                (user_id, ticker, alert_type, message, severity, sent, sent),
            )


def _ticker_name(ticker: str) -> Optional[str]:
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM tickers WHERE ticker = %s", (ticker,))
            r = cur.fetchone()
            return r[0] if r else None


# ---- Driver ------------------------------------------------------------

def _site_base_url() -> str:
    """Site root for stock-detail deep links. Set via WEB_BASE_URL env;
    default is the current Vercel prod hostname. Trailing slash stripped
    so callers can just concat `/stocks/{ticker}`."""
    url = os.environ.get("WEB_BASE_URL") or "https://thesauros2026.vercel.app"
    return url.rstrip("/")


# alert_type → (Korean label, action ask). The label tells the user
# WHICH alert preference toggle fired the message ("진입 신호" / "청산
# 신호" 등 — matches the toggle names on /settings). The ask is the
# 책-tone one-liner: 매매는 안 할수록 좋고 좋은 자리만 — so we say
# "검토" / "점검" / "원칙대로", not "지금 사세요".
_ALERT_TYPE_META: Dict[str, Tuple[str, str, str]] = {
    # alert_type → (badge, korean label, action ask)
    "enter":   ("🟢", "진입 신호",  "지금 자리인지 점검"),
    "pyramid": ("🟡", "추가매수",   "이미 보유 중이면 비중 추가 검토"),
    "warn":    ("🟠", "경고",       "수익 보전 / 비중 축소 시점 점검"),
    "exit":    ("🔴", "청산 신호",  "추세 종료 — 청산 검토"),
    "target":  ("🎯", "목표가",     "목표가 도달 — 일부 익절 검토"),
    "stop":    ("🛑", "손절가",     "손절가 도달 — 원칙대로 매도"),
}


def _clean_name(name: Optional[str]) -> str:
    """Trim whitespace + collapse the awkward 'Name  - Common Stock'
    suffix Naver pads onto US tickers. Without this the title becomes
    'TSLA Tesla, Inc.  - Common Stock · 진입 신호' — verbose without
    adding info beyond 'Tesla, Inc.'."""
    if not name:
        return ""
    n = " ".join(name.split())   # collapse internal whitespace
    for suffix in (" - Common Stock", " - Class A Common Stock",
                   " - Class B Common Stock"):
        if n.endswith(suffix):
            n = n[: -len(suffix)]
            break
    return n.strip()


def format_message(ticker: str, name: Optional[str], alert_type: str,
                   sig: Dict[str, Any]) -> str:
    """Telegram alert message — book-tone, action-first, deep-linkable.

    Layout:

        {badge} {alert_type 한글} — <b>{ticker}</b> {name}
        {signal phrase 한 줄} — {action ask}

        📈 multi-TF stack (월/주/일)
        🎯 freshness — fresh/late/invalid
        💰 외인+기관 동행 (KR only)
        📊 강도/신뢰도/종합 점수

        🔔 알림 설정 "{한글 label}" 에서 발송됨
        👉 <a href="...">상세 분석 보기 →</a>

    Body is HTML (parse_mode=HTML). The first two lines answer "뭐 어쩌
    라는 건지" (what kind of alert + what action is implied); the footer
    answers "어떤 알림 설정이 보냈는지" + gives a one-click deep link
    into the site's /stocks/{ticker} page so the user can verify the
    underlying data without typing the ticker into a search box.
    """
    signal_type = sig.get("signal_type", "")
    label = _signal_label(signal_type)

    badge, atype_label, action_ask = _ALERT_TYPE_META.get(
        alert_type, ("📊", alert_type, "확인"),
    )
    name_clean = _clean_name(name)

    # Title row: badge · 한글 alert_type · ticker · 종목명
    # The dash before name groups "{ticker} {name}" visually so the
    # name is read as an annotation, not part of the alert label.
    title_name = f" {name_clean}" if name_clean else ""
    title = f"{badge} <b>{atype_label}</b> — <b>{ticker}</b>{title_name}"

    # Action line: combines the signal's descriptive phrase with the
    # book-tone action ask. e.g. "쌍바닥 매수 반전 패턴 — 지금 자리인지 점검".
    lines = [title, f"📊 {label['phrase']} — {action_ask}"]

    # Multi-TF stack from analyze_results.
    blob = _analyze_blob(ticker)
    trend = (blob or {}).get("trend") or {}
    tf_parts: List[str] = []
    for tf_key, tf_label in (("monthly", "월"), ("weekly", "주"), ("daily", "일")):
        t = trend.get(tf_key)
        if not t:
            continue
        align = t.get("alignment_score")
        arrow = "↑" if (t.get("above_ma_10") and (align or 0) >= 0.6) else \
                ("→" if t.get("above_ma_10") else "↓")
        tf_parts.append(
            f"{tf_label}{arrow}{(f' {align:.0%}' if isinstance(align, (int, float)) else '')}"
        )
    if tf_parts:
        lines.append("📈 " + "  ".join(tf_parts))

    # Freshness line — mirrors the FreshnessChip used on every web page.
    # Tells the user whether this BUY signal is a "right now" entry or
    # already +70% past the breakout. Without this a STRONG_BUY alert on
    # a stale ticker looks identical to one fired on a fresh breakout.
    fresh = _freshness_of(blob) if (blob and label["dir"] == "bull") else None
    if fresh:
        zone = _fresh_zone_label(fresh["runup"])
        lines.append(
            f"🎯 {fresh['kind']} 돌파 {fresh['runup']:+.0f}% — {zone}"
        )

    # Smart-money corroboration (KR only). Placed before the score row
    # because it's narrative ("외인+기관이 같이 사고 있다") — easier to
    # read in sequence with the multi-TF + freshness lines than after
    # the numeric strength/confidence summary.
    flow = _flow_5d(ticker)
    if flow:
        f, i = flow["foreign"], flow["inst"]
        if label["dir"] == "bull" and f > 0 and i > 0:
            lines.append(
                f"💰 외인+기관 동행 매수 (5일 합: 외인 {f / 1e9:+.1f}B · 기관 {i / 1e9:+.1f}B)"
            )
        elif label["dir"] == "bear" and f < 0 and i < 0:
            lines.append(
                f"💰 외인+기관 동행 매도 (5일 합: 외인 {f / 1e9:+.1f}B · 기관 {i / 1e9:+.1f}B)"
            )

    # Strength + confidence row — quantitative tail, after the
    # narrative. Same numbers users see on the stock page so the
    # alert + page agree.
    strength = sig.get("strength")
    conf = (sig.get("params") or {}).get("confidence")
    score = (blob or {}).get("book_score")
    bits: List[str] = []
    if strength is not None:
        bits.append(f"강도 {float(strength):.2f}")
    if isinstance(conf, (int, float)):
        bits.append(f"신뢰도 {float(conf):.0%}")
    if isinstance(score, (int, float)):
        bits.append(f"종합 {float(score):+.2f}")
    if bits:
        lines.append("📊 " + " · ".join(bits))

    # Footer — answers "어떤 알림 설정이 이걸 보냈는지" + deep-link to
    # the stock page. Blank line first so the footer reads as metadata,
    # not part of the signal narrative.
    lines.append("")
    lines.append(f'🔔 알림 설정 "{atype_label}" 에서 발송됨')
    lines.append(
        f'👉 <a href="{_site_base_url()}/stocks/{ticker}">'
        f'상세 분석 보기 →</a>'
    )

    return "\n".join(lines)


def _check_price_targets(
    user_id: str, w: Dict[str, Any]
) -> List[Tuple[str, Dict[str, Any]]]:
    """Returns list of (alert_type, sig) for any newly-hit target/stop."""
    out: List[Tuple[str, Dict[str, Any]]] = []
    ticker = w["ticker"]
    last = _latest_close(ticker)
    if last is None:
        return out

    # ---- Target (one-shot: only if not already hit) ------------------
    if w.get("target_hit_at") is None:
        tgt = w.get("target_price")
        if tgt is None and w.get("entry_price") and w.get("target_pct_from_entry") is not None:
            tgt = float(w["entry_price"]) * (1.0 + float(w["target_pct_from_entry"]))
        if tgt is not None and last >= float(tgt):
            _mark_hit(user_id, ticker, "target_hit_at")
            out.append(("target", {
                "reason": f"종가 {last:,.2f} ≥ 목표 {float(tgt):,.2f}",
                "timeframe": "daily",
                "detected_at": "now()",
                "strength": None,
                "signal_type": "watchlist_target_hit",
            }))

    # ---- Stop (one-shot) --------------------------------------------
    if w.get("stop_hit_at") is None:
        stop = w.get("stop_price")
        if stop is None and w.get("entry_price") and w.get("stop_pct_from_entry") is not None:
            stop = float(w["entry_price"]) * (1.0 + float(w["stop_pct_from_entry"]))
        if stop is not None and last <= float(stop):
            _mark_hit(user_id, ticker, "stop_hit_at")
            out.append(("stop", {
                "reason": f"종가 {last:,.2f} ≤ 손절 {float(stop):,.2f}",
                "timeframe": "daily",
                "detected_at": "now()",
                "strength": None,
                "signal_type": "watchlist_stop_hit",
            }))
    return out


def run_once(dry_run: bool = False) -> Dict[str, int]:
    stats = {"users": 0, "watched_tickers": 0, "new_alerts": 0, "sent": 0,
             "pushed": 0, "skipped_existing": 0}

    users = _users_with_alerts()
    stats["users"] = len(users)
    if not users:
        log.info("no users with telegram or push subscriptions")
        return stats

    for u in users:
        watch = _watchlist_active(u["id"])
        if not watch:
            continue
        prefs = _user_prefs(u["id"])
        tickers = [w["ticker"] for w in watch]
        category_by_ticker = {w["ticker"]: w["category"] for w in watch}
        watch_by_ticker = {w["ticker"]: w for w in watch}
        stats["watched_tickers"] += len(tickers)
        signals = _active_signals_for(tickers)

        # group scan signals by (ticker, alert_type) — keep highest strength
        best: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for s in signals:
            cls = classify(s["signal_type"])
            if not cls:
                continue
            atype, sev = cls
            if atype == "pyramid" and category_by_ticker.get(s["ticker"]) != "holding":
                continue
            k = (s["ticker"], atype)
            if k not in best or float(s["strength"] or 0) > float(best[k]["strength"] or 0):
                best[k] = {**s, "alert_type": atype, "severity": sev}

        # add per-user price target / stop alerts (one-shot via *_hit_at)
        for w in watch:
            for atype, sig in _check_price_targets(u["id"], w):
                sev = "critical" if atype == "stop" else "info"
                best[(w["ticker"], atype)] = {
                    **sig, "alert_type": atype, "severity": sev,
                    "ticker": w["ticker"],
                }

        for (ticker, atype), sig in best.items():
            # respect alert_preferences toggles
            pref_key = _PREF_BY_ALERT.get(atype)
            if pref_key and not prefs.get(pref_key, True):
                continue
            sig_at = sig.get("detected_at") or "1970-01-01"
            if sig_at != "now()" and _already_alerted(u["id"], ticker, atype, sig_at):
                stats["skipped_existing"] += 1
                continue
            name = _ticker_name(ticker)
            msg = format_message(ticker, name, atype, sig)
            sent = False
            if not dry_run:
                if u.get("telegram_chat_id"):
                    sent = send_telegram(u["telegram_chat_id"], msg)
                if u.get("has_push") and webpush_available():
                    subs = _push_subs_for(u["id"])
                    push_label = _signal_label(sig.get("signal_type", ""))
                    push_body = push_label["phrase"]
                    strength = sig.get("strength")
                    if strength is not None:
                        push_body = f"{push_body} · 강도 {float(strength):.2f}"
                    payload = {
                        "title": f"{push_label['name']} · {ticker} {name or ''}".strip(),
                        "body": push_body[:200],
                        "tag": f"{atype}:{ticker}",
                        "url": f"/stocks/{ticker}",
                        "severity": sig["severity"],
                    }
                    result = send_many(subs, payload)
                    stats["pushed"] += len(result["sent"])
                    _delete_push_subs(result["gone"])
                _insert_alert(u["id"], ticker, atype, msg, sig["severity"], sent)
            stats["new_alerts"] += 1
            if sent:
                stats["sent"] += 1
                # Telegram global limit: ~30 msg/sec for all chats. With ~20
                # msg/sec we stay safely under (and per-chat limit of 1 msg/sec
                # is naturally respected — we only send 1 message per
                # ticker×alert_type per user, so a single user almost never
                # gets 2 messages back-to-back).
                time.sleep(0.05)
    return stats


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true",
                   help="don't send telegram messages or insert rows")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    stats = run_once(dry_run=args.dry_run)
    log.info("done: %s", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
