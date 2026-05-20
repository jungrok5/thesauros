/**
 * Pure aggregation helpers for /flow-ranking — kept separate from the
 * server-component page so they can be unit-tested without spinning up
 * Supabase + Next request scope.
 */

export type RawFlowRow = {
  ticker: string;
  day: string;
  foreign_net: string | number | null;
  institution_net: string | number | null;
};

export type AggregatedFlow = {
  ticker: string;
  foreign_sum: number;
  institution_sum: number;
  combined_sum: number;
  days: number;
};

/** Group by ticker, sum foreign + institution net flow. Coerces
 * stringy numeric values (PostgREST returns numeric as string) and
 * nulls to 0. Days counter is "rows seen for this ticker", which
 * doubles as a freshness/coverage signal in the UI. */
export function aggregateFlowRows(rows: RawFlowRow[]): AggregatedFlow[] {
  const agg = new Map<string, { f: number; i: number; days: number }>();
  for (const r of rows) {
    const cur = agg.get(r.ticker) ?? { f: 0, i: 0, days: 0 };
    cur.f += Number(r.foreign_net ?? 0);
    cur.i += Number(r.institution_net ?? 0);
    cur.days += 1;
    agg.set(r.ticker, cur);
  }
  const out: AggregatedFlow[] = [];
  for (const [ticker, v] of agg.entries()) {
    out.push({
      ticker,
      foreign_sum: v.f,
      institution_sum: v.i,
      combined_sum: v.f + v.i,
      days: v.days,
    });
  }
  return out;
}

export function sortAndTake(
  rows: AggregatedFlow[],
  direction: "buy" | "sell",
  limit: number,
): AggregatedFlow[] {
  const sorted = [...rows].sort((a, b) =>
    direction === "buy"
      ? b.combined_sum - a.combined_sum
      : a.combined_sum - b.combined_sum,
  );
  return sorted.slice(0, limit);
}

/** Format KRW for display. 조 / 억 / 만 thresholds match the rest of
 * the site so a number that prints as "5억" on /flow-ranking also
 * prints as "5억" on the dashboard. */
export function fmtKRW(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1e12) return `${(v / 1e12).toFixed(1)}조`;
  if (abs >= 1e8) return `${(v / 1e8).toFixed(0)}억`;
  if (abs >= 1e4) return `${(v / 1e4).toFixed(0)}만`;
  return v.toLocaleString("ko-KR");
}
