/**
 * Regression: AVOID/SELL/SELL_OR_SHORT 종목을 신규 보유로 추가하려고
 * 할 때 사용자에게 window.confirm 으로 한 번 경고 한다.
 * (2026-05-21 — "AVOID 종목도 + 보유 막힘 없이 추가 가능했던" UX 약점 fix).
 *
 * If someone removes the confirm gate, this test fails.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { cleanup, render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

afterEach(cleanup);

import { WatchlistButton } from "@/components/watchlist-button";

// Mock fetch + router so the button can be interacted with.
const originalFetch = globalThis.fetch;
beforeEach(() => {
  globalThis.fetch = vi.fn(async () =>
    new Response(JSON.stringify({ ok: true }), { status: 200 }),
  ) as unknown as typeof fetch;
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: () => {} }),
}));

describe("WatchlistButton — AVOID 종목 + 보유 confirm guard", () => {
  it("AVOID 종목 '+ 보유' 클릭 시 window.confirm 호출", () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<WatchlistButton ticker="TEST.KS" action="AVOID" />);
    fireEvent.click(screen.getByTestId("watchlist-holding"));
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    const msg = String(confirmSpy.mock.calls[0]?.[0] ?? "");
    expect(msg).toMatch(/신규 매수 자격 X|매수 자격 X/);
  });

  it("SELL 종목 '+ 보유' 클릭 시도 confirm 호출", () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<WatchlistButton ticker="TEST.KS" action="SELL" />);
    fireEvent.click(screen.getByTestId("watchlist-holding"));
    expect(confirmSpy).toHaveBeenCalledTimes(1);
  });

  it("SELL_OR_SHORT 도 confirm 호출", () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<WatchlistButton ticker="TEST.KS" action="SELL_OR_SHORT" />);
    fireEvent.click(screen.getByTestId("watchlist-holding"));
    expect(confirmSpy).toHaveBeenCalledTimes(1);
  });

  it("STRONG_BUY 종목 '+ 보유' 클릭 시 confirm 호출 X (자유)", () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<WatchlistButton ticker="TEST.KS" action="STRONG_BUY" />);
    fireEvent.click(screen.getByTestId("watchlist-holding"));
    expect(confirmSpy).not.toHaveBeenCalled();
  });

  it("AVOID 종목이라도 '+ 관심' (observing) 은 confirm 안 함 — 모니터링 free", () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<WatchlistButton ticker="TEST.KS" action="AVOID" />);
    fireEvent.click(screen.getByTestId("watchlist-observing"));
    expect(confirmSpy).not.toHaveBeenCalled();
  });

  it("confirm cancel 시 fetch 호출 안 됨 — 추가 안 됨", () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<WatchlistButton ticker="TEST.KS" action="AVOID" />);
    fireEvent.click(screen.getByTestId("watchlist-holding"));
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it("confirm OK 시 fetch 호출 됨 — 추가 진행", () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<WatchlistButton ticker="TEST.KS" action="AVOID" />);
    fireEvent.click(screen.getByTestId("watchlist-holding"));
    expect(globalThis.fetch).toHaveBeenCalled();
  });
});
