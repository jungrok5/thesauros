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
    # Universe-winner book-spirit entries (sweep_per_signal_sl + production
    # backtest top-5). Added 2026-05-26 so Telegram alerts ≡ /screener
    # signal set. Previously these fired in scan_results and were visible
    # on the dashboard, but never reached subscribed users.
    # (2026-05-27: BookEntrySpots removed; /screener is the only candidate
    # surface, alignment goal unchanged.)
    ("volume_case_3",           "enter",    "info"),
    ("volume_case_7",           "enter",    "info"),
    ("pattern_forking",         "enter",    "info"),
    ("pattern_ma240_breakout",  "enter",    "info"),
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

    `bedrest_mode` (migration 044) — 책 2부 3장 "한달 누워있다 1회만
    확인" 정신. ON 이면 run_once 가 이 user 의 모든 즉시 alert 를 skip.

    Graceful degradation (회고 #2): migration 044 미적용 DB 시
    (bedrest_mode 컬럼 자체 없을 때) UndefinedColumn 발생. fallback 으로
    bedrest_mode 없는 SELECT 재시도 + bedrest 기본 False 처리.
    """
    DEFAULTS_ALL_ON = {
        "enable_enter": True, "enable_pyramid": True,
        "enable_warn": True, "enable_exit": True,
        "enable_ma240_break": True,
        "enable_quarter_25_break": True,
        "bedrest_mode": False,
    }
    try:
        with get_conn(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT enable_enter, enable_pyramid, enable_warn, "
                    "enable_exit, enable_ma240_break, enable_quarter_25_break, "
                    "bedrest_mode "
                    "FROM alert_preferences WHERE user_id = %s",
                    (user_id,),
                )
                r = cur.fetchone()
                if not r:
                    return DEFAULTS_ALL_ON
                keys = [d[0] for d in cur.description]
                return {k: bool(v) for k, v in zip(keys, r)}
    except Exception as e:
        # bedrest_mode 컬럼이 없는 환경 (migration 044 미적용) 또는 다른
        # transient error. bedrest 기본값 (false) 으로 fallback — 사용자가
        # silent 무알림 되는 사고 방지.
        log.warning(
            "_user_prefs SELECT failed (%s) — falling back to all-on defaults",
            str(e).splitlines()[0][:200],
        )
        return DEFAULTS_ALL_ON


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
    "pattern_ma240_breakout":             {"name": "240MA 돌파",   "dir": "bull", "phrase": "240MA 돌반지 — 책의 돌파매매 옥석"},
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
    # 회고 #55 — ALERT_RULES 에 있지만 _SIGNAL_LABELS 누락이던 4 개.
    # 한글 label 없으면 사용자에게 raw snake_case 노출.
    "pattern_death_messenger": {"name": "저승사자",     "dir": "bear", "phrase": "장대음봉 + 주봉 10MA 동시 이탈 (저승사자)"},
    "ma240_break_down":        {"name": "240MA 이탈",  "dir": "bear", "phrase": "월봉 240MA 하향 돌파 (죽은 차트 진입)"},
    "pattern_cup_and_handle":  {"name": "컵핸들",      "dir": "bull", "phrase": "컵 위드 핸들 매수 추세 지속"},
    "pattern_doulbanji":       {"name": "돌반지",      "dir": "bull", "phrase": "240MA 돌파-지지-반등 (책의 최강 매수 시그널)"},
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


def _is_month_end_week(today=None) -> bool:
    """True iff this week's Friday is the LAST Friday of its calendar
    month — proxy for 책의 '월말 영업일 분석'. The Friday of the next
    week is in the following month iff today's Friday is the last.

    책 2부 3장: "월봉 = 매월 말일 오후 2시 1회 확인". Adding a
    dedicated monthly cron would mean a new GH workflow + Vercel cron +
    KR-holiday calendar — book-spirit "안 할수록 좋다" pushes against
    that. Embedding the cue in weekly-scan's existing alert is cheaper
    and produces the same nudge: "이번 주가 월말 주 — 월봉 신호도
    함께 점검".
    """
    from datetime import date, timedelta
    d = today or date.today()
    # KST cron runs Friday — use today as the anchor.
    # Find this week's Friday (today if Friday, otherwise the upcoming).
    # weekday(): Mon=0 .. Sun=6. Friday = 4.
    days_to_fri = (4 - d.weekday()) % 7
    this_friday = d + timedelta(days=days_to_fri)
    next_friday = this_friday + timedelta(days=7)
    return next_friday.month != this_friday.month


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


# Alert types that represent "사야 하나" decisions — these get gated
# by buy eligibility so the telegram message matches what the
# stock-detail NoviceVerdict card says. Exit-class alerts (exit / stop
# / warn) are always sent regardless of eligibility — a SELL signal
# fires whether or not the user could have bought.
_ENTER_CLASS_ALERTS = {"enter", "pyramid", "target"}

# eligibility.reason_code values that mean "page is explicitly saying
# 자리 X" (NOT just "자리 지남"). For these we DROP the alert entirely
# rather than downgrade — the page would tell the user not to buy and
# a telegram alert would directly contradict.
_DROP_ELIGIBILITY_REASONS = {"ambush", "stale", "post_rally"}


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
                   sig: Dict[str, Any],
                   source: Optional[str] = None) -> str:
    """Telegram alert message — book-tone, action-first, deep-linkable.

    Layout:

        {badge} [<b>{source}</b>] {alert_type 한글} — <b>{ticker}</b> {name}
        📊 {eligibility headline — body, or fallback signal phrase + ask}
        📈 multi-TF stack (월/주/일)
        🎯 freshness — fresh/late/invalid
        💰 외인+기관 동행 (KR only)
        📊 강도/신뢰도/종합 점수

        👉 다음 단계 (enter-class only):
           1) 차트 직접 확인 (월/주/일 정배열 맞나)
           2) 분할 매수 시작 (한 번에 다 X)
           3) 손절가 미리 설정 (-7%)

        📅 매수 결정은 금요일 15:30 종가 기준 · 일중 흔들림 무시.
        🔔 알림 설정 "{한글 label}" 에서 발송됨
        👉 <a href="...">상세 분석 보기 →</a>

    source — which list this came from: "관심" / "보유" / "모의투자".
    When None (legacy callers), the bracket is omitted so older code
    paths still render cleanly. Body is HTML (parse_mode=HTML).

    Beginner-friendly redesign (2026-05-27): added the [source] tag so
    the user knows which list triggered the alert, and the 다음 단계
    block so they don't have to guess what action follows an enter-
    class signal. The "매수 결정은 금요일 종가 기준" reminder is on
    every alert because users keep acting on intraday wiggles.
    """
    signal_type = sig.get("signal_type", "")
    label = _signal_label(signal_type)

    badge, atype_label, action_ask = _ALERT_TYPE_META.get(
        alert_type, ("📊", alert_type, "확인"),
    )
    name_clean = _clean_name(name)

    # Read eligibility from the analyze_results blob — this is the
    # same verdict the page's NoviceVerdict card shows. When it
    # disagrees with the raw alert_type (e.g. action=BUY but
    # eligibility says CONDITIONAL — 자리 지남), the message must
    # reflect the eligibility, not the raw classifier. Otherwise
    # the alert and the page tell two different stories about the
    # same ticker (the 2026-05-22 TSLA incident).
    blob = _analyze_blob(ticker)
    elig = (blob or {}).get("eligibility") or {}
    elig_grade = elig.get("grade")
    elig_icon = elig.get("icon")
    elig_headline = elig.get("headline")
    elig_body = elig.get("body")

    # Title — for enter-class alerts that are CONDITIONAL, swap the
    # badge to the page's downgrade icon and tag the label with
    # "(조건부)" so the user knows up-front this isn't a clean buy
    # signal.
    is_enter_class = alert_type in _ENTER_CLASS_ALERTS
    if is_enter_class and elig_grade == "CONDITIONAL" and elig_icon:
        title_badge = elig_icon
        title_label = f"{atype_label} (조건부)"
    else:
        title_badge = badge
        title_label = atype_label

    title_name = f" {name_clean}" if name_clean else ""
    # [source] tag — "관심" / "보유" / "모의투자". Omitted for legacy
    # callers that pass source=None so older tests still pass.
    source_tag = f"[{source}] " if source else ""
    title = f"{title_badge} <b>{source_tag}{title_label}</b> — <b>{ticker}</b>{title_name}"

    # Action line — prefer eligibility headline+body for enter-class
    # alerts since that's the exact wording the user sees on the
    # stock page. Falls back to the generic phrase+ask when eligibility
    # is unavailable (older analyze_results without the field).
    if is_enter_class and elig_headline:
        if elig_body:
            lines = [title, f"📊 {elig_headline} — {elig_body}"]
        else:
            lines = [title, f"📊 {elig_headline}"]
    else:
        lines = [title, f"📊 {label['phrase']} — {action_ask}"]
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

    # "다음 단계" guide — enter / pyramid only (true entry signals).
    # target 은 _ENTER_CLASS 에 포함되지만 익절 알림이라 "분할 매수"
    # 가이드는 부적절. exit/warn/stop 은 자체 action_ask 가 있고,
    # target 은 paper alerts 의 익절 메시지와 합칠 일이라 enter 가이드
    # 와 분리. 사용자가 "알림 왔는데 뭘 해야 하지?" 묻는 가장 흔한
    # 시나리오 = 진입 신호 처음 받았을 때.
    if alert_type in {"enter", "pyramid"}:
        lines.append("")
        lines.append("👉 다음 단계:")
        lines.append("   1) 차트 직접 확인 (월/주/일 정배열 맞나)")
        lines.append("   2) 분할 매수 시작 (한 번에 다 X)")
        lines.append("   3) 손절가 미리 설정 (-7% 권장)")

    # Footer — answers "어떤 알림 설정이 이걸 보냈는지" + deep-link to
    # the stock page. Blank line first so the footer reads as metadata,
    # not part of the signal narrative.
    lines.append("")
    # 책 정신 reminder — 매수 결정은 주봉 종가 기준이라 일중 흔들림으로
    # 액션하지 말라는 거. 매 알림에 박아두는 게 초보자 panic-trading
    # 방지에 가장 효과적 (관심 종목 가격 흔들리면 텔레그램부터 보는
    # 패턴이므로).
    lines.append(
        "📅 매수 결정은 금요일 15:30 종가 기준 · 일중 흔들림 무시."
    )
    # 월말 주 강조 — 책 2부 3장의 "월봉 1회 확인" 정신. 매주 평소처럼
    # 같은 알림이 오더라도, 그 주가 월말 주이면 사용자가 "월봉도 함께
    # 점검" 하도록 헤더 한 줄로 nudge.
    if _is_month_end_week():
        lines.append("📅 이번 주 = 월말 주 — 월봉 240MA / 포킹 함께 점검")
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
             "pushed": 0, "skipped_existing": 0, "bedrest_skipped": 0,
             "skipped_locked": 0}

    # 2026-05-28 — postgres advisory lock guards against the race where
    # multiple Analyze-Single-Ticker workflows (dispatched in parallel
    # by watchlist API on consecutive adds) each kick off telegram_worker
    # simultaneously. Each instance reads `alerts` before any has had a
    # chance to insert → dedup window misses → every active signal sends
    # twice (or more). Pinning a single global slot for telegram_worker
    # makes the "already alerted" check a hard serialization point.
    #
    # The lock is session-scoped (auto-released on conn close), so we
    # hold the conn open for the entire run. pg_try_advisory_lock
    # returns False immediately if held by another session — that
    # invocation just exits as no-op.
    _TG_WORKER_LOCK_KEY = 0x7E1E_670A_C001  # arbitrary bigint constant
    from contextlib import contextmanager

    @contextmanager
    def _exclusive_lock():
        with get_conn(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(%s)",
                            (_TG_WORKER_LOCK_KEY,))
                acquired = bool(cur.fetchone()[0])
            try:
                yield acquired
            finally:
                if acquired:
                    with conn.cursor() as cur:
                        cur.execute("SELECT pg_advisory_unlock(%s)",
                                    (_TG_WORKER_LOCK_KEY,))

    with _exclusive_lock() as acquired:
        if not acquired:
            log.info(
                "telegram_worker advisory lock held by another session — "
                "skipping (concurrent dispatch detected)",
            )
            stats["skipped_locked"] = 1
            return stats
        return _run_once_locked(stats, dry_run)


def _run_once_locked(stats: Dict[str, int], dry_run: bool) -> Dict[str, int]:
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
        # 와병투자 모드 — 책 2부 3장 정신. ON 인 사용자에게는 어떠한
        # 즉시 alert 도 보내지 않는다. 별도 weekly digest 가 그 역할을
        # 대신함 (P1 weekly-scan 구현 후 enable 예정).
        if prefs.get("bedrest_mode"):
            stats["bedrest_skipped"] += 1
            log.info("skip user %s — bedrest_mode ON", u["id"])
            continue
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
            # Eligibility gate (added 2026-05-22) — enter-class alerts
            # must respect the same buy-eligibility verdict the page
            # NoviceVerdict card shows. Background: cron sent jungrok5
            # a "🟢 진입 신호 TSLA" while the page simultaneously said
            # "⚠️ 매수 자격: 조건부 — 지금은 자리 X". The page is the
            # source of truth (its gates are book-spirit); the alert
            # was misleading. We drop enter-class alerts when the
            # page would say "자리 X" (ambush / stale-pattern /
            # post-rally), and downgrade them visually when the page
            # says "조건부 — 자리 지남". Exit / warn / stop alerts pass
            # through unchanged regardless of eligibility.
            if atype in _ENTER_CLASS_ALERTS:
                _elig = (_analyze_blob(ticker) or {}).get("eligibility") or {}
                _grade = _elig.get("grade")
                _reason = _elig.get("reason_code")
                if _grade == "CONDITIONAL" and _reason in _DROP_ELIGIBILITY_REASONS:
                    log.info(
                        "skip %s/%s — eligibility CONDITIONAL reason=%s "
                        "(page would say 자리 X)",
                        ticker, atype, _reason,
                    )
                    continue
                # WATCH/AVOID/EXIT shouldn't appear for an enter-class
                # signal (classifier would map to a different alert),
                # but defense-in-depth: never enter-alert on a chart
                # the page calls 회피/매도.
                if _grade in {"AVOID", "EXIT"}:
                    log.info("skip %s/%s — eligibility=%s", ticker, atype, _grade)
                    continue
            sig_at = sig.get("detected_at") or "1970-01-01"
            if sig_at != "now()" and _already_alerted(u["id"], ticker, atype, sig_at):
                stats["skipped_existing"] += 1
                continue
            name = _ticker_name(ticker)
            # source = "관심" / "보유" so the message header tells the
            # user which list this came from (2026-05-27 redesign).
            _cat = category_by_ticker.get(ticker)
            _source = "보유" if _cat == "holding" else "관심"
            msg = format_message(ticker, name, atype, sig, source=_source)
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


def run_bedrest_digest(dry_run: bool = False) -> Dict[str, int]:
    """Weekly digest for bedrest_mode users (회고 #1).

    매주 weekly-scan 의 telegram step 직후 실행. bedrest_mode=true 인
    사용자 각각의 watchlist 에서 **이번 주에 새로 발견된 active enter/exit
    신호** 만 모아 1통의 요약 메시지로 발송. 책 정신: "한달 누워있다 1회만
    확인" — 사용자는 주 1회만 신호 본다.
    """
    stats = {"users": 0, "sent": 0, "skipped_no_signals": 0}

    # bedrest 사용자만 — _users_with_alerts 와 join.
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.id::text, u.telegram_chat_id
                  FROM users u
                  JOIN alert_preferences ap ON ap.user_id = u.id
                 WHERE ap.bedrest_mode = true
                   AND u.telegram_chat_id IS NOT NULL
                   AND u.telegram_chat_id <> ''
                """
            )
            users = cur.fetchall()
    stats["users"] = len(users)
    if not users:
        log.info("no bedrest users")
        return stats

    for user_id, chat_id in users:
        watch = _watchlist_active(user_id)
        if not watch:
            stats["skipped_no_signals"] += 1
            continue
        tickers = [w["ticker"] for w in watch]
        signals = _active_signals_for(tickers)
        # 책 정신 매매 결정 = enter/exit class only — 와병투자 digest 는
        # 정말 매매할 만한 신호만 모음. warn / pyramid 등은 noise.
        actionable = [s for s in signals if classify(s["signal_type"]) and
                      classify(s["signal_type"])[0] in {"enter", "exit"}]
        if not actionable:
            stats["skipped_no_signals"] += 1
            continue

        # 메시지 — 책 톤. enter / exit 분리, ticker 최대 5개씩 list.
        enter_lines: List[str] = []
        exit_lines: List[str] = []
        for s in actionable[:30]:   # safety cap
            atype = classify(s["signal_type"])[0]
            label = _signal_label(s["signal_type"])
            line = f"  · <b>{s['ticker']}</b> {label['name']}"
            if atype == "enter":
                enter_lines.append(line)
            else:
                exit_lines.append(line)

        sections: List[str] = []
        if enter_lines:
            sections.append("🟢 <b>매수 후보</b> (책 점검 자리)\n" + "\n".join(enter_lines[:10]))
        if exit_lines:
            sections.append("🔴 <b>청산 신호</b> (보유 중이면 검토)\n" + "\n".join(exit_lines[:10]))

        msg = (
            "🛌 <b>와병투자 주간 요약</b>\n"
            "이번 주 watchlist 의 결정-grade 신호 모음. 본인 차트 검증 후 진행.\n\n"
            + "\n\n".join(sections)
        )
        if not dry_run and chat_id:
            ok = send_telegram(chat_id, msg)
            if ok:
                stats["sent"] += 1
                time.sleep(0.05)
    return stats


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true",
                   help="don't send telegram messages or insert rows")
    p.add_argument("--digest", action="store_true",
                   help="와병투자 주간 요약 모드 (bedrest_mode=true 사용자에게만)")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if args.digest:
        stats = run_bedrest_digest(dry_run=args.dry_run)
        log.info("digest done: %s", stats)
    else:
        stats = run_once(dry_run=args.dry_run)
        log.info("done: %s", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
