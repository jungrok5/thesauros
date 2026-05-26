/**
 * BookEntrySpots — dashboard "책 정신 매수 후보 TOP 3" card.
 *
 * 2026-05-26 — rewritten after the data-source unification. Component
 * now calls the screener_results RPC (same as /screener page) so the
 * dashboard preview = first 3 rows of the screener list, 1:1.
 *
 * Tests mock the Supabase RPC call and assert UI invariants:
 *   - default limit = 3 (the alignment fix)
 *   - empty state when RPC returns []
 *   - row rendering + 더보기 link to /screener
 *   - SL ON badge only for STRONG_BUY or volume_case_3
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import fs from "node:fs";
import path from "node:path";

const mockRpc = vi.fn();

// F6 (2026-05-26): BookEntrySpots now also queries analyze_results
// for eligibility chips. Tests mock the `.from(...).select(...).in(...)
// .limit(...)` chain so the component renders end-to-end. Tests that
// don't care about chips just leave the eligibility query empty.
const mockEligibilityFrom = vi.fn();

vi.mock("@/lib/supabase", () => ({
  getServerClient: () => ({
    rpc: mockRpc,
    from: (_: string) => ({
      select: (_s: string) => ({
        in: (_col: string, _vals: string[]) => ({
          limit: (_n: number) => mockEligibilityFrom(),
        }),
      }),
    }),
  }),
}));

beforeEach(() => {
  vi.resetModules();
  mockRpc.mockReset();
  // Default: no eligibility data, no chips. Tests that exercise chip
  // rendering can mockResolvedValueOnce a different payload.
  mockEligibilityFrom.mockResolvedValue({ data: [], error: null });
});
afterEach(() => cleanup());

describe("BookEntrySpots", () => {
  it("renders empty-state when RPC returns no rows", async () => {
    mockRpc.mockResolvedValueOnce({ data: [], error: null });
    const mod = await import("@/components/book-entry-spots");
    const view = await mod.BookEntrySpots();
    render(view);
    expect(screen.getByText(/책 정신 매수 후보.*종목이 없습니다/))
      .toBeInTheDocument();
  });

  it("renders TOP 3 rows from screener_results RPC", async () => {
    mockRpc.mockResolvedValueOnce({
      data: [
        { ticker: "339950.KQ", name: "테스트A", action: "STRONG_BUY",
          book_score: "1.00", roe: "0.25", volume_case_num: 3,
          catalyst_bars_since: 2 },
        { ticker: "078520.KS", name: "테스트B", action: "BUY",
          book_score: "0.95", roe: "0.18", volume_case_num: 7,
          catalyst_bars_since: 5 },
        { ticker: "066620.KQ", name: "테스트C", action: "STRONG_BUY",
          book_score: "0.92", roe: "0.12", volume_case_num: null,
          catalyst_bars_since: null },
      ],
      error: null,
    });
    const mod = await import("@/components/book-entry-spots");
    const view = await mod.BookEntrySpots();
    const { container } = render(view);
    expect(screen.getByText(/테스트A/)).toBeInTheDocument();
    expect(screen.getByText(/테스트B/)).toBeInTheDocument();
    expect(screen.getByText(/테스트C/)).toBeInTheDocument();
    // STRONG_BUY + volume_case_3 → SL ON (10%) for row 1
    // BUY + volume_case_7 → SL OFF for row 2
    // STRONG_BUY w/o volume case → SL ON (10%) for row 3 (rule is OR)
    const text = container.textContent ?? "";
    expect((text.match(/10%/g) ?? []).length).toBeGreaterThanOrEqual(2);
    expect(text).toContain("OFF");
  });

  it("dashboard preview defaults to TOP 3", async () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, "..", "components", "book-entry-spots.tsx"),
      "utf8",
    );
    expect(src).toMatch(/const DEFAULT_LIMIT = 3;/);
  });

  it("renders 스크리너 더보기 link to /screener when there are spots", async () => {
    mockRpc.mockResolvedValueOnce({
      data: [
        { ticker: "005930.KS", name: "삼성전자", action: "BUY",
          book_score: "0.85", roe: "0.15", volume_case_num: null,
          catalyst_bars_since: null },
      ],
      error: null,
    });
    const mod = await import("@/components/book-entry-spots");
    const view = await mod.BookEntrySpots({ limit: 3 });
    const { container } = render(view);
    const moreLink = container.querySelector('a[href="/screener"]');
    expect(moreLink, "BookEntrySpots must link to /screener").not.toBeNull();
    expect(moreLink?.textContent).toMatch(/스크리너/);
  });

  // 2026-05-26 alignment guard — the unification commit must keep using
  // the screener_results RPC. If anyone reverts to direct scan_results
  // (the pre-unification source), this fails.
  it("uses screener_results RPC, not direct scan_results access", async () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, "..", "components", "book-entry-spots.tsx"),
      "utf8",
    );
    expect(src).toMatch(/screener_results/);
    expect(src).not.toMatch(/\.from\(\s*["']scan_results["']/);
  });
});
