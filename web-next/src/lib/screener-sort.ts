/**
 * Book-spirit sort for screener rows.
 *
 * 2026-05-27 → 2026-05-29 history:
 *   - L2: 0.8 × book + 0.2 × cap_q (today snapshot). Backtest reported
 *     CAGR +20.65 / Sharpe 0.83 / Alpha +11.36 — Phase 9 PIT verification
 *     proved ~+12 pp of that CAGR was look-ahead bias (today's "mid-cap"
 *     correlates with "winner over hold period" by construction).
 *   - Honest: drop cap_q (CAP_WEIGHT=0), keep book_score only. Sector
 *     diversification handled via sector_cap=1/ISO-week in the
 *     production backtest, NOT here — screener sort is per-snapshot, no
 *     concept of "weeks".
 *
 * Honest 17.4y backtest (sector_cap=1 + book-only):
 *   CAGR +16.02% / Sharpe 0.73 / DD 48.2% / Alpha +7.20%/y vs KOSPI BH.
 *   Slippage-adjusted realistic CAGR ~14%.
 *
 * Priority:
 *   1. eligibility grade   OK > CONDITIONAL > WATCH > AVOID > unknown
 *   2. book_score          DESC (cap is no longer reweighted)
 *   3. catalyst freshness  ASC  (catalyst_bars_since, null = oldest)
 *   4. ROE                 DESC (final tie-break)
 *   5. ticker              ASC  (stable)
 *
 * bookSpiritScore signature kept for call-site compatibility; the cap
 * argument is now ignored.
 */

import { bookSpiritScore } from "@/lib/book-spirit-ranking";

export type EligibilityGrade = "OK" | "CONDITIONAL" | "WATCH" | "AVOID";

export interface SortableHit {
  ticker: string;
  book_score: number | null;
  roe: number | null;
  catalyst_bars_since: number | null;
  eligibility_grade?: EligibilityGrade | null;
  market_cap?: number | null;
}

const GRADE_RANK: Record<EligibilityGrade, number> = {
  OK: 0,
  CONDITIONAL: 1,
  WATCH: 2,
  AVOID: 3,
};

export function sortByBookSpirit<T extends SortableHit>(hits: T[]): T[] {
  return [...hits].sort((a, b) => {
    const ga = a.eligibility_grade ? GRADE_RANK[a.eligibility_grade] ?? 0 : 0;
    const gb = b.eligibility_grade ? GRADE_RANK[b.eligibility_grade] ?? 0 : 0;
    if (ga !== gb) return ga - gb;
    const sa = bookSpiritScore(a.book_score, a.market_cap);
    const sb = bookSpiritScore(b.book_score, b.market_cap);
    if (sa !== sb) return sb - sa;
    const ca = a.catalyst_bars_since ?? 999;
    const cb = b.catalyst_bars_since ?? 999;
    if (ca !== cb) return ca - cb;
    const ra = a.roe ?? 0;
    const rb = b.roe ?? 0;
    if (ra !== rb) return rb - ra;
    return a.ticker.localeCompare(b.ticker);
  });
}
