/**
 * Pins the 2026-05-28 KR-only autocomplete contract. Earlier the
 * /api/search route would return US tickers (NASDAQ/NYSE/AMEX) in two
 * paths:
 *   1. The local DB query had no market filter — tickers seeded as
 *      NASDAQ/NYSE would surface.
 *   2. The Naver merge accepted both nation=KR and nation=US hits.
 *
 * Site is KR-focused; US analysis isn't wired into the screener/chart/
 * eligibility surfaces, so US hits were dead-ends ("AAPL 검색되지만
 * 분석 안 됨"). Source-level static check guards the two filters.
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

describe("/api/search — KR-only autocomplete", () => {
  const src = readFileSync(
    resolve(__dirname, "../app/api/search/route.ts"),
    "utf-8",
  );

  it("local DB query filters tickers.market to KOSPI/KOSDAQ", () => {
    // PostgREST .in("market", ["KOSPI", "KOSDAQ"]) — pin both terms.
    expect(src).toMatch(/\.in\(\s*["']market["']\s*,\s*\[\s*["']KOSPI["']\s*,\s*["']KOSDAQ["']\s*\]\s*\)/);
  });

  it("Naver merge skips non-KR hits", () => {
    // The merge loop must skip hits whose nation !== "KR".
    expect(src).toMatch(/h\.nation\s*!==\s*["']KR["']/);
  });

  it("does not include any literal NASDAQ/NYSE/AMEX market in the merge", () => {
    // Defensive: nobody should have re-added a US-friendly carve-out.
    expect(src).not.toMatch(/["'](NASDAQ|NYSE|AMEX)["']/);
  });
});
