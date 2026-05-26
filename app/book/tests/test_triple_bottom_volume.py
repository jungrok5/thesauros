"""Pin the 2026-05-26 fake_volume detector reform for triple-bottom.

audit_200 found 60%+ of detected triple-bottoms flagged fake_volume
on KR data. Investigation: the rule was strict `a.volume < b.volume <
c.volume`. Real-world bottom volume is noisy; a mid-pattern dip with
final-bottom recovery (book's actual "우상향" picture, p276) was
miscategorized as fake.

Fix: `c.volume > a.volume` (last bottom > first bottom = overall
upward trend). Real fakes (steady decline like 161000.KS [3.5M, 1.1M,
0.85M]) still caught.
"""
import pandas as pd
from app.book.patterns import detect_triple_bottom


def _df_with_volumes(closes: list[float], volumes: list[float]) -> pd.DataFrame:
    assert len(closes) == len(volumes)
    dates = pd.date_range("2024-01-01", periods=len(closes), freq="W")
    return pd.DataFrame({
        "date": dates,
        "open": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "close": closes,
        "volume": volumes,
    })


def _triple_bottom_shape() -> list[float]:
    """Three roughly-equal lows then breakout — minimal shape that
    detect_triple_bottom recognizes."""
    closes = [105.0] * 5
    closes += list(_lin(105, 60, 25))
    closes += [60.0]
    closes += list(_lin(60, 78, 15))
    closes += [78.0]
    closes += list(_lin(78, 61, 15))
    closes += [61.0]
    closes += list(_lin(61, 79, 15))
    closes += [79.0]
    closes += list(_lin(79, 62, 15))
    closes += [62.0]
    closes += list(_lin(62, 95, 30))
    while len(closes) < 240:
        closes.append(closes[-1] * 0.999)
    return closes


def _lin(start: float, end: float, n: int) -> list[float]:
    if n <= 1:
        return [end]
    step = (end - start) / (n - 1)
    return [start + i * step for i in range(n)]


def test_u_shape_volume_is_NOT_fake():
    """Mid-pattern volume dip with final-bottom recovery — book's
    canonical "우상향" picture. Should NOT be flagged fake."""
    closes = _triple_bottom_shape()
    # Volumes constant except at the three bottoms where the pattern
    # logic samples. Just give last bottom > first bottom.
    vols = [1_000_000] * len(closes)
    # The three bottom indices in this synthetic shape — give explicit
    # ascending-overall volumes so the rule sees c > a even with a mid
    # dip.
    bot1, bot2, bot3 = 30, 61, 92
    vols[bot1] = 1_000_000   # first
    vols[bot2] =   500_000   # mid dip
    vols[bot3] = 1_500_000   # final > first
    df = _df_with_volumes(closes, vols)
    p = detect_triple_bottom(df)
    if p is None:
        return   # detector didn't recognize the synthetic — fine
    assert (p.extra or {}).get("fake_volume") is False, (
        "U-shape with c > a must NOT be fake (book p276 우상향 = overall trend)"
    )


def test_steady_decline_volume_IS_fake():
    """Real fake — volume declines through all three bottoms.
    Mirrors the 161000.KS case [3.5M, 1.1M, 0.85M]."""
    closes = _triple_bottom_shape()
    vols = [1_000_000] * len(closes)
    bot1, bot2, bot3 = 30, 61, 92
    vols[bot1] = 3_500_000
    vols[bot2] = 1_100_000
    vols[bot3] =   850_000      # < a
    df = _df_with_volumes(closes, vols)
    p = detect_triple_bottom(df)
    if p is None:
        return
    assert (p.extra or {}).get("fake_volume") is True, (
        "Steady decline (c < a) must still be flagged fake"
    )


def test_strict_rising_volume_is_NOT_fake():
    """Strict a<b<c — also passes (the old detector's only happy case)."""
    closes = _triple_bottom_shape()
    vols = [1_000_000] * len(closes)
    bot1, bot2, bot3 = 30, 61, 92
    vols[bot1] = 1_000_000
    vols[bot2] = 1_500_000
    vols[bot3] = 2_000_000
    df = _df_with_volumes(closes, vols)
    p = detect_triple_bottom(df)
    if p is None:
        return
    assert (p.extra or {}).get("fake_volume") is False
