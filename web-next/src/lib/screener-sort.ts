/**
 * Book-spirit single sort for screener rows. Replaces the
 * applySort2 (2026-05-21 "5 sort options") UX after user feedback
 * (2026-05-26): "정렬 옵션 많고 뭐가 뭔지 모름 — 가장 책에 부합하는
 * 주식이 누군지 알 수 있게 정렬해줘."
 *
 * Priority (eligibility-first is the critical change vs old sort):
 *   1. eligibility grade  OK > CONDITIONAL > WATCH > AVOID > unknown
 *   2. book_score         DESC (signal strength)
 *   3. catalyst freshness ASC  (catalyst_bars_since, null = oldest)
 *   4. ROE                DESC (final tie-break)
 *   5. ticker             ASC  (stable)
 *
 * Why eligibility outranks book_score:
 *   339950.KQ (책 점수 1.0, eligibility CONDITIONAL "박스권 횡보, 진입
 *   자리 X") was outranking 003650.KS (책 점수 1.0, eligibility OK
 *   "강한 매수 가능") because the old sort tie-broke on ROE. Book says
 *   신호 강도 만점이라도 진입 자리 아니면 매수 X — so the safety gate
 *   has to outrank signal score.
 *
 * Unknown grade (legacy analyze_results rows pre-eligibility-pipeline)
 * ranks AS OK so they aren't punished for being old; the chip simply
 * won't render. Once everything is re-scanned this is moot.
 */

export type EligibilityGrade = "OK" | "CONDITIONAL" | "WATCH" | "AVOID";

export interface SortableHit {
  ticker: string;
  book_score: number | null;
  roe: number | null;
  catalyst_bars_since: number | null;
  eligibility_grade?: EligibilityGrade | null;
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
    const sa = a.book_score ?? 0;
    const sb = b.book_score ?? 0;
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
