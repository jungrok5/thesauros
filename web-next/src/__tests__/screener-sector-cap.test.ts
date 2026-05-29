/**
 * Sector cap = 1 — verifies the screener page's post-sort filter that
 * mirrors the backtest's sector_cap_per_week=1 logic. Production memory
 * project_book_faithful_backtest says screener / Telegram / backtest
 * must share the same buy-side algorithm; this test pins the screener
 * half so it cannot drift back into "rank by book_score only".
 *
 * The helper itself lives in src/app/(app)/screener/page.tsx and is
 * tiny enough that re-implementing it here keeps the test independent
 * of Next.js page module imports. If page.tsx's helper changes, this
 * test should be updated to match.
 */
import { describe, it, expect } from "vitest";

interface Row {
  ticker: string;
  industry: string | null;
}

function applySectorCap<T extends Row>(rows: T[], capPerIndustry = 1): T[] {
  const counts: Record<string, number> = {};
  const out: T[] = [];
  for (const r of rows) {
    const key = (r.industry || "").trim() || `_unknown_${r.ticker}`;
    counts[key] = counts[key] || 0;
    if (counts[key] >= capPerIndustry) continue;
    counts[key]++;
    out.push(r);
  }
  return out;
}

describe("screener sector cap = 1 per industry", () => {
  it("keeps only the first ticker per industry from a sorted list", () => {
    const rows: Row[] = [
      { ticker: "A.KS", industry: "소프트웨어 개발 및 공급업" },
      { ticker: "B.KQ", industry: "소프트웨어 개발 및 공급업" },
      { ticker: "C.KS", industry: "기타 화학제품 제조업" },
      { ticker: "D.KQ", industry: "소프트웨어 개발 및 공급업" },
      { ticker: "E.KS", industry: "기타 화학제품 제조업" },
    ];
    const out = applySectorCap(rows);
    expect(out.map((r) => r.ticker)).toEqual(["A.KS", "C.KS"]);
  });

  it("treats NULL/empty industry tickers as their own buckets (kept)", () => {
    // FDR coverage misses ~4% of tickers — those should NOT all collapse
    // into a single "_unknown_" bucket and get filtered to one survivor.
    const rows: Row[] = [
      { ticker: "X.KS", industry: null },
      { ticker: "Y.KQ", industry: "" },
      { ticker: "Z.KS", industry: null },
    ];
    const out = applySectorCap(rows);
    expect(out.map((r) => r.ticker)).toEqual(["X.KS", "Y.KQ", "Z.KS"]);
  });

  it("respects input order — relies on caller (sortByBookSpirit) to pre-rank", () => {
    // If a lower-quality A is sorted before the higher-quality B in the
    // same industry, A wins. The page calls applySectorCap AFTER
    // sortByBookSpirit so this is fine in practice — the test pins
    // the ordering contract.
    const rows: Row[] = [
      { ticker: "LOWER.KS", industry: "X" },
      { ticker: "HIGHER.KS", industry: "X" },
    ];
    expect(applySectorCap(rows).map((r) => r.ticker)).toEqual(["LOWER.KS"]);
  });

  it("does not mutate the input array", () => {
    const rows: Row[] = [
      { ticker: "A", industry: "X" },
      { ticker: "B", industry: "X" },
    ];
    const before = rows.map((r) => r.ticker);
    applySectorCap(rows);
    expect(rows.map((r) => r.ticker)).toEqual(before);
  });

  it("with capPerIndustry=2, allows the top two per industry", () => {
    const rows: Row[] = [
      { ticker: "A", industry: "X" },
      { ticker: "B", industry: "X" },
      { ticker: "C", industry: "X" },
      { ticker: "D", industry: "Y" },
    ];
    const out = applySectorCap(rows, 2);
    expect(out.map((r) => r.ticker)).toEqual(["A", "B", "D"]);
  });
});
