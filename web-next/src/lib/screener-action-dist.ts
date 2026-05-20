/**
 * Action distribution helper for the screener page.
 *
 * Lives in lib (not the page) so a vitest can lock in the bucketing —
 * specifically that SELL_OR_SHORT (which appears in
 * `AnalysisResult.action`) is counted as "avoid" and NOT silently
 * dropped. The bug we're guarding against: value-classic returned 35
 * candidates, 24 of which were SELL_OR_SHORT — the original page
 * counter only bucketed AVOID/SELL, so those 24 appeared invisible
 * and the user could read 1위 as 강매수 by accident.
 */

export type ActionDistribution = {
  strong_buy: number;
  buy: number;
  hold: number;
  avoid: number;   // AVOID + SELL + SELL_OR_SHORT
  none: number;
};

export function actionDistribution(
  rows: Array<{ action: string | null }>,
): ActionDistribution {
  const d: ActionDistribution = {
    strong_buy: 0,
    buy: 0,
    hold: 0,
    avoid: 0,
    none: 0,
  };
  for (const r of rows) {
    switch (r.action) {
      case "STRONG_BUY":
        d.strong_buy += 1;
        break;
      case "BUY":
        d.buy += 1;
        break;
      case "HOLD":
        d.hold += 1;
        break;
      case "AVOID":
      case "SELL":
      case "SELL_OR_SHORT":
        d.avoid += 1;
        break;
      default:
        d.none += 1;
    }
  }
  return d;
}
