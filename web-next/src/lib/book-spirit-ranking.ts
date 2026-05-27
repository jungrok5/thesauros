/**
 * L2 mid-cap sweet spot ranking — production formula picked from
 * 2026-05-27 grid search (14 variants, 17y backtest).
 *
 * Result: CAGR +20.65%, DD 37.3%, Sharpe 0.83, Calmar 0.55, alpha +11.36%/y.
 * Beats book-only baseline by +5.75%p CAGR and -14.2%p DD.
 *
 * Score = 0.8 × book_score + 0.2 × cap_q
 *
 * cap_q is a log-scale tent peaking at ~5,480억 KRW (sqrt of 3000억 × 1조):
 *   • cap ≤ 500억 → 0    (microcap excluded — 작전주/관리종목 risk)
 *   • cap = 500억 ~ peak → linear up on log10
 *   • cap = peak (~5,480억) → 1
 *   • cap = peak ~ 10조 → linear down on log10
 *   • cap ≥ 10조 → 0     (mega-cap excluded — already crowded by funds)
 *
 * Result of the grid: KR mid-caps in this range have enough liquidity to
 * trade clean but are not yet fully priced by institutions — book signal
 * survives there.
 */

const CAP_LOW_KRW  = 5e10;   // 500억 — microcap exclusion floor
const CAP_HIGH_KRW = 1e13;   // 10조  — mega-cap exclusion ceiling
const CAP_MID_LO   = 3e11;   // 3000억
const CAP_MID_HI   = 1e12;   // 1조

const LOG_LO   = Math.log10(CAP_LOW_KRW);
const LOG_HI   = Math.log10(CAP_HIGH_KRW);
const LOG_PEAK = (Math.log10(CAP_MID_LO) + Math.log10(CAP_MID_HI)) / 2;

export const BOOK_WEIGHT = 0.8;
export const CAP_WEIGHT  = 0.2;

/** Tent-shape cap quality in [0, 1]. Returns 0 when cap is null/0/out-of-range. */
export function capQuality(marketCapKrw: number | null | undefined): number {
  if (marketCapKrw == null || marketCapKrw <= 0) return 0;
  const lc = Math.log10(marketCapKrw);
  if (lc <= LOG_LO || lc >= LOG_HI) return 0;
  if (lc <= LOG_PEAK) return (lc - LOG_LO) / (LOG_PEAK - LOG_LO);
  return (LOG_HI - lc) / (LOG_HI - LOG_PEAK);
}

/** Combined L2 score in [0, 1]. */
export function bookSpiritScore(
  bookScore: number | null | undefined,
  marketCapKrw: number | null | undefined,
): number {
  const b = bookScore ?? 0;
  const q = capQuality(marketCapKrw);
  return BOOK_WEIGHT * b + CAP_WEIGHT * q;
}
