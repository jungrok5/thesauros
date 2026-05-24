/**
 * UsAnalysisSearch — client search/result component for US ad-hoc
 * book analysis (Phase 6).
 *
 * Tests:
 *   1. Submit triggers fetch to /api/us-analysis with the ticker.
 *   2. Loading + error states render.
 *   3. Result renders headline stats (last close, 240MA, etc).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { UsAnalysisSearch } from "@/components/us-analysis-search";

const originalFetch = global.fetch;
const mockFetch = vi.fn();

beforeEach(() => {
  global.fetch = mockFetch as unknown as typeof fetch;
  mockFetch.mockReset();
});

afterEach(() => {
  cleanup();
  global.fetch = originalFetch;
});

describe("UsAnalysisSearch", () => {
  it("calls /api/us-analysis on submit", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        ticker: "AAPL", fetched_now: true, bars_count: 261,
        first_bar: "2021-05-24", last_bar: "2026-05-22",
        meta: { name: "Apple Inc.", exchange: "NASDAQ" },
        analysis: { last_close: 200, book_score: 0.4,
                    trend: { weekly: { ma_240: 150, book_signal: "uptrend" } } },
      }),
    });
    render(<UsAnalysisSearch />);
    const input = screen.getByPlaceholderText(/AAPL/);
    fireEvent.change(input, { target: { value: "AAPL" } });
    fireEvent.click(screen.getByText("분석"));
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        "/api/us-analysis?ticker=AAPL",
        expect.objectContaining({ method: "GET" }),
      );
    });
    await waitFor(() => {
      expect(screen.getByText(/Apple Inc\./)).toBeInTheDocument();
    });
    expect(screen.getByText(/240MA \(주봉\)/)).toBeInTheDocument();
  });

  it("renders error state on API failure", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ error: "ticker not found: ZZZZ" }),
      status: 404,
    });
    render(<UsAnalysisSearch />);
    fireEvent.change(screen.getByPlaceholderText(/AAPL/), {
      target: { value: "ZZZZ" },
    });
    fireEvent.click(screen.getByText("분석"));
    await waitFor(() => {
      expect(screen.getByText(/ticker not found/)).toBeInTheDocument();
    });
  });
});
