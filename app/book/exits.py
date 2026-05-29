"""책의 매도 신호 — backtest + Telegram alert 가 공유하는 pure 함수.

세 가지 매도 룰을 single source of truth 로 캡슐화. portfolio_book.py
(백테스트) 와 db.notify_book_exits (알림) 가 동일한 정의를 사용해서
"한 알고리즘, 세 얼굴" 원칙 보장.

1) is_jangdae_yangbong(...)        — 책 엔진의 장대양봉 판정 (app/book/
                                     candles.py:172 정식 정의: body ≥
                                     최근 N-bar 평균 body × 2 + 양봉).
2) quartile_25_level(open_, close) — 책 p218-223 의 4등분선 (25%) 기준선.
3) monthly_10ma_broken(closes)     — 책의 단일 가장 객관적 추세선
                                     (월봉 종가 < 10-month MA).

각 함수는 (entry_bar 정보 또는 가격 시계열) 만 입력으로 받고 부울/실수만
반환. DB 연결 X, side-effect X — backtest 와 alerter 가 같은 입력에
같은 출력을 보장.
"""
from __future__ import annotations

from typing import Sequence

# Book engine equivalent: body must be at least N× the rolling avg body
# of the prior N bars. app/book/candles.py uses 2.0 with body_avg from
# the classifier's caller; pin both here.
LONG_BULLISH_BODY_MULT = 2.0
LONG_BULLISH_AVG_WINDOW = 20

# Tent quartile retracement threshold; "절대 자리 깨짐" line.
QUARTILE_25 = 0.25

# Monthly trend gauge — book's "가장 객관적인 추세선".
MONTHLY_MA_WINDOW = 10


def is_jangdae_yangbong(
    open_: float, close: float, recent_avg_body: float,
    body_mult: float = LONG_BULLISH_BODY_MULT,
) -> bool:
    """True iff (close > open) AND (close - open) ≥ recent_avg_body × body_mult.

    `recent_avg_body` is the rolling-mean absolute body of the prior N
    bars (caller-supplied so the function stays pure). Pass 0 or
    negative to disable the size check — useful for unit tests but
    NEVER in production (would tag every bullish bar as 장대).
    """
    if close <= open_ or open_ <= 0:
        return False
    if recent_avg_body <= 0:
        return False
    return (close - open_) >= recent_avg_body * body_mult


def quartile_25_level(open_: float, close: float) -> float:
    """For a 장대양봉 (open..close body), the 25% retracement level.

    Closes below this level mean book's "절대 자리 깨짐" → exit.
    """
    body = close - open_
    return open_ + QUARTILE_25 * body


def monthly_10ma_broken(
    monthly_closes: Sequence[float],
    ma_window: int = MONTHLY_MA_WINDOW,
) -> bool:
    """True iff the latest monthly close is strictly below the simple
    `ma_window`-month moving average of the closes.

    `monthly_closes` must be in chronological order, oldest → newest.
    Returns False when fewer than `ma_window` bars are present (no
    well-defined MA yet) so newly-listed names can't fire spurious
    exits.
    """
    if len(monthly_closes) < ma_window:
        return False
    window = list(monthly_closes[-ma_window:])
    if any(c is None for c in window):
        return False
    avg = sum(window) / float(ma_window)
    return monthly_closes[-1] < avg
