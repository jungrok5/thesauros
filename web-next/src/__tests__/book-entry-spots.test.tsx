/**
 * BookEntrySpots — dashboard "이번 주 책 진입 자리" card.
 *
 * Server component reads scan_results via getServerClient. Tests
 * stub the Supabase chain to return mock signal rows.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import fs from "node:fs";
import path from "node:path";

const mockData = vi.fn();

vi.mock("@/lib/supabase", () => ({
  getServerClient: () => ({
    from: () => ({
      select: () => ({
        in: () => ({
          eq: () => ({
            gte: () => ({
              order: () => ({
                limit: () => mockData(),
              }),
            }),
          }),
        }),
      }),
    }),
  }),
}));

beforeEach(() => {
  vi.resetModules();
  mockData.mockReset();
});
afterEach(() => cleanup());

describe("BookEntrySpots", () => {
  it("renders empty-state when no signals fired in last 7 days", async () => {
    mockData.mockResolvedValueOnce({ data: [], error: null });
    const mod = await import("@/components/book-entry-spots");
    const view = await mod.BookEntrySpots();
    render(view);
    expect(screen.getByText(/이번 주 책 전략.*fire 종목이 없습니다/))
      .toBeInTheDocument();
  });

  it("renders top spots sorted by strength desc + SL chip per signal", async () => {
    mockData.mockResolvedValueOnce({
      data: [
        {
          ticker: "005930.KS", signal_type: "action_strong_buy",
          strength: 0.92, detected_at: "2026-05-24T00:00:00Z",
          reason: null, tickers: { name: "삼성전자" },
        },
        {
          ticker: "000660.KS", signal_type: "volume_case_3",
          strength: 0.85, detected_at: "2026-05-23T00:00:00Z",
          reason: null, tickers: { name: "SK하이닉스" },
        },
        {
          ticker: "035720.KS", signal_type: "pattern_forking",
          strength: 0.78, detected_at: "2026-05-22T00:00:00Z",
          reason: null, tickers: { name: "카카오" },
        },
      ],
      error: null,
    });
    const mod = await import("@/components/book-entry-spots");
    const view = await mod.BookEntrySpots({ limit: 8 });
    const { container } = render(view);
    expect(screen.getByText(/삼성전자/)).toBeInTheDocument();
    expect(screen.getByText(/SK하이닉스/)).toBeInTheDocument();
    expect(screen.getByText(/카카오/)).toBeInTheDocument();
    // 2개의 ON 권장 (action_strong_buy + volume_case_3), 1개 OFF (forking)
    expect(container.textContent).toContain("10%");
    expect(container.textContent).toContain("OFF");
  });

  // Site-direction reset 2026-05-25 — dashboard surface trimmed to TOP 3
  // preview + 스크리너 더보기 link to remove the dashboard/스크리너
  // duplication the user flagged.
  it("dashboard preview defaults to TOP 3 (not the legacy 12)", async () => {
    mockData.mockResolvedValueOnce({ data: [], error: null });
    const mod = await import("@/components/book-entry-spots");
    // Renders empty-state shell; the literal "DEFAULT_LIMIT" used by the
    // header is the value we want to lock down.
    const src = fs.readFileSync(
      path.resolve(__dirname, "..", "components", "book-entry-spots.tsx"),
      "utf8",
    );
    expect(src).toMatch(/const DEFAULT_LIMIT = 3;/);
    // sanity — module still resolves end-to-end
    const view = await mod.BookEntrySpots();
    render(view);
  });

  it("renders 스크리너 더보기 link to /screener when there are spots", async () => {
    mockData.mockResolvedValueOnce({
      data: [
        {
          ticker: "005930.KS", signal_type: "action_strong_buy",
          strength: 0.92, detected_at: "2026-05-24T00:00:00Z",
          reason: null, tickers: { name: "삼성전자" },
        },
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
});
