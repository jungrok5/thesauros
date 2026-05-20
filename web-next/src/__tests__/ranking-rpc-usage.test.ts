/**
 * Lock down the PostgREST 1000-row hard-cap regression (2026-05-20):
 *
 *   /flow-ranking and /volume-surge previously did
 *     sb.from("investor_flow").select(...).gte("day", since)
 *   on tables with ~27K matching rows. PostgREST max_rows is hard-
 *   capped at 1000 (status 206 + Content-Range header), so the JS-
 *   side aggregation only saw 4% of the universe — rankings were
 *   wrong without any explicit error.
 *
 *   Fix: replaced the table query with `sb.rpc("top_flow_rankings", ...)`
 *   / `sb.rpc("volume_surges", ...)`, which run GROUP BY server-side
 *   and return ~30 already-aggregated rows. The page files must NOT
 *   contain the old direct-table query pattern anymore.
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import { join } from "path";

const APP = join(__dirname, "..", "app", "(app)");

function read(...parts: string[]): string {
  return readFileSync(join(APP, ...parts), "utf-8");
}

describe("ranking pages use server-side aggregation (RPC)", () => {
  it("/flow-ranking calls top_flow_rankings RPC", () => {
    const src = read("flow-ranking", "page.tsx");
    expect(src).toMatch(/\.rpc\(["']top_flow_rankings["']/);
  });

  it("/flow-ranking does NOT direct-select from investor_flow (1000-row cap)", () => {
    const src = read("flow-ranking", "page.tsx");
    expect(src).not.toMatch(/sb\.from\(["']investor_flow["']\)\.select/);
  });

  it("/volume-surge calls volume_surges RPC", () => {
    const src = read("volume-surge", "page.tsx");
    expect(src).toMatch(/\.rpc\(["']volume_surges["']/);
  });

  it("/volume-surge does NOT direct-select bars with granularity=W (1000-row cap)", () => {
    const src = read("volume-surge", "page.tsx");
    expect(src).not.toMatch(
      /sb\.from\(["']bars["']\)\.select\([^)]*\)[\s\S]{0,200}?\.eq\(["']granularity["'],\s*["']W["']\)/
    );
  });
});

describe("/screener uses server-side RPC (no JS aggregation)", () => {
  it("calls screener_results RPC", () => {
    const src = read("screener", "page.tsx");
    expect(src).toMatch(/\.rpc\(["']screener_results["']/);
  });

  it("calls screener_action_distribution RPC", () => {
    const src = read("screener", "page.tsx");
    expect(src).toMatch(/\.rpc\(["']screener_action_distribution["']/);
  });

  it("does NOT direct-select from factors_eval (the old 3-query + JS sort pattern)", () => {
    const src = read("screener", "page.tsx");
    expect(src).not.toMatch(/sb\.from\(["']factors_eval["']\)\.select/);
  });

  it("does NOT direct-fetch analyze_results in bulk (the old N+1-ish pattern)", () => {
    const src = read("screener", "page.tsx");
    expect(src).not.toMatch(
      /sb\.from\(["']analyze_results["']\)\.select\([^)]*\)\.in\(/
    );
  });
});
