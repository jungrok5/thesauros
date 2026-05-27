/**
 * Book-spirit sort for screener rows.
 *
 * 2026-05-27 — replaced the secondary "book_score only" tier with the
 * L2 mid-cap sweet score (winner of the 14-variant Phase 1-4 grid:
 * CAGR +20.65%, DD 37.3%, Calmar 0.55, alpha +11.36%/y vs KOSPI).
 * Formula lives in [[book-spirit-ranking]].
 *
 * Priority:
 *   1. eligibility grade   OK > CONDITIONAL > WATCH > AVOID > unknown
 *   2. bookSpiritScore     DESC (= 0.8×book_score + 0.2×cap_tent_q)
 *   3. catalyst freshness  ASC  (catalyst_bars_since, null = oldest)
 *   4. ROE                 DESC (final tie-break)
 *   5. ticker              ASC  (stable)
 *
 * Why eligibility still outranks the L2 score: signal strength + mid-cap
 * tilt say "good buy candidate"; eligibility (F7-F14 gates) say "we are
 * actually at a buy spot". A 1.0 score at the wrong moment is still not
 * a buy. Order = safety gate first, then ranking.
 *
 * Unknown grade ranks AS OK so legacy rows aren't punished; once
 * everything is re-scanned this is moot.
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
