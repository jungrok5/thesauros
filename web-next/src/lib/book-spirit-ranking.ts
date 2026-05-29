/**
 * Honest production ranking — book signal only + sector_cap=1 (enforced
 * downstream in screener / sort, not in this scoring function).
 *
 * History:
 *   - 2026-05-27 L2: 0.8 × book + 0.2 × cap_q (today snapshot) → claimed
 *     CAGR +20.65% / Sharpe 0.83 / Alpha +11.36%/y.
 *   - 2026-05-29 Phase 9 verification: applying the SAME formula with
 *     PIT (point-in-time) cap dropped CAGR to +8.07% and Sharpe to 0.34.
 *     The +12 pp CAGR gap is look-ahead bias — today-snapshot cap_q
 *     systematically biases toward tickers that grew INTO mid-cap over
 *     the holding period (= winners by construction).
 *   - Decision: drop cap_q entirely. Use sector cap (1 per ISO-week per
 *     industry) for diversification — the only Phase 5-8 factor that
 *     survived the look-ahead audit.
 *
 * Honest backtest (sector_cap=1 + book-only, 17.4y, 2009-2026):
 *   CAGR +16.02%, Sharpe 0.73, DD 48.2%, Alpha +7.20%/y (vs KOSPI BH).
 *   Realistic ~14% CAGR after un-modeled slippage (~2pp/y drag).
 *
 * Score formula:
 *   score = book_score    (cap is no longer reweighted)
 *
 * The capQuality function remains exported but unused in the score —
 * kept around so the dashboard's old "mid-cap sweet spot" tooltip
 * (where present) can still render historical comparisons.
 */

const CAP_LOW_KRW  = 5e10;   // 500억
const CAP_HIGH_KRW = 1e13;   // 10조
const CAP_MID_LO   = 3e11;
const CAP_MID_HI   = 1e12;

const LOG_LO   = Math.log10(CAP_LOW_KRW);
const LOG_HI   = Math.log10(CAP_HIGH_KRW);
const LOG_PEAK = (Math.log10(CAP_MID_LO) + Math.log10(CAP_MID_HI)) / 2;

/**
 * 2026-05-29 — book_weight raised from 0.8 → 1.0 after Phase 9 PIT
 * verification proved cap_q was a look-ahead artifact. CAP_WEIGHT = 0
 * means cap_q never enters the score; legacy callers that pass cap get
 * the same score they would have with cap=null.
 */
export const BOOK_WEIGHT = 1.0;
export const CAP_WEIGHT  = 0.0;

/** Tent-shape cap quality in [0, 1]. Unused in scoring (CAP_WEIGHT=0)
 * but retained for diagnostic / display purposes. */
export function capQuality(marketCapKrw: number | null | undefined): number {
  if (marketCapKrw == null || marketCapKrw <= 0) return 0;
  const lc = Math.log10(marketCapKrw);
  if (lc <= LOG_LO || lc >= LOG_HI) return 0;
  if (lc <= LOG_PEAK) return (lc - LOG_LO) / (LOG_PEAK - LOG_LO);
  return (LOG_HI - lc) / (LOG_HI - LOG_PEAK);
}

/**
 * Honest score in [0, 1] = book_score. The second argument is kept for
 * call-site compatibility with prior L2 sites; it is ignored.
 */
export function bookSpiritScore(
  bookScore: number | null | undefined,
  _marketCapKrw?: number | null,
): number {
  return bookScore ?? 0;
}
