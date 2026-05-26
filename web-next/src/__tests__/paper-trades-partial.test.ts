/**
 * Phase 4 — partial close (분할 매도) on /paper.
 *
 * The split logic itself lives in the API route as two Supabase
 * writes (update existing row + insert closed row). We can't run
 * Supabase in unit tests, but the *aggregation* logic — once the
 * DB has split rows — must keep adding up to "what the user
 * actually invested vs what they have now". computeStats handles
 * that, so the tests below pin its behavior on shapes the partial-
 * close flow produces.
 */
import { describe, it, expect } from "vitest";
import { computeStats, type PaperTradeLive } from "@/lib/paper-trades";

function row(overrides: Partial<PaperTradeLive>): PaperTradeLive {
  return {
    id: crypto.randomUUID(),
    user_id: "u1",
    ticker: "TEST.KS",
    entry_date: "2026-05-01",
    entry_price: 100,
    amount_krw: 1_000_000,
    shares: 10_000,
    stop_loss: 90,
    target: 120,
    notes: null,
    status: "open",
    exit_date: null,
    exit_price: null,
    exit_reason: null,
    created_at: "2026-05-01T00:00:00Z",
    current_price: 115,
    current_value_krw: 1_150_000,
    pnl_krw: 150_000,
    pnl_pct: 15,
    stop_hit: false,
    target_hit: false,
    ...overrides,
  };
}

describe("paper-trades — partial close (Phase 4) aggregation", () => {
  it("two open lots on same ticker (추매) sum into total invested", () => {
    const s = computeStats([
      row({ amount_krw: 1_000_000, current_value_krw: 1_100_000,
            notes: "first" }),
      row({ amount_krw: 500_000,   current_value_krw: 550_000,
            notes: "추매" }),
    ]);
    expect(s.open_n).toBe(2);
    expect(s.total_invested_krw).toBe(1_500_000);
    expect(s.total_current_value_krw).toBe(1_650_000);
    expect(s.total_pnl_pct).toBeCloseTo(10.0, 1);
  });

  it("after 50% partial close: open lot half + new closed row at +15%", () => {
    // Shape the partial-close API leaves behind: original row shrunk
    // to 50% (open), new immediately-closed row at the current price.
    const s = computeStats([
      row({                                        // remaining open half
        amount_krw: 500_000,
        shares: 5_000,
        current_value_krw: 575_000,
        pnl_pct: 15,
        notes: "first",
      }),
      row({                                        // realized partial sell
        amount_krw: 500_000,
        shares: 5_000,
        status: "closed_manual",
        exit_date: "2026-05-15",
        exit_price: 115,
        exit_reason: "수동 청산",
        current_price: 115,
        current_value_krw: 575_000,
        pnl_krw: 75_000,
        pnl_pct: 15,
        notes: "first · 분할 매도 (50%)",
      }),
    ]);
    expect(s.open_n).toBe(1);
    expect(s.closed_n).toBe(1);
    expect(s.total_invested_krw).toBe(500_000);    // remaining open only
    expect(s.win_rate).toBe(1);                    // 1 of 1 closed = win
    expect(s.avg_pnl_pct).toBeCloseTo(15, 2);
    expect(s.best_pct).toBe(15);
    expect(s.worst_pct).toBe(15);
  });

  it("partial close followed by full close: both closed rows counted", () => {
    const s = computeStats([
      // First partial: 50% sold at +20%
      row({ status: "closed_manual", amount_krw: 500_000,
            shares: 5_000, exit_price: 120, exit_date: "2026-05-10",
            pnl_pct: 20, current_price: 120 }),
      // Then full close of remaining 50% at +10%
      row({ status: "closed_manual", amount_krw: 500_000,
            shares: 5_000, exit_price: 110, exit_date: "2026-05-20",
            pnl_pct: 10, current_price: 110 }),
    ]);
    expect(s.open_n).toBe(0);
    expect(s.closed_n).toBe(2);
    expect(s.win_rate).toBe(1);
    expect(s.avg_pnl_pct).toBeCloseTo(15, 2);       // mean of 20, 10
    expect(s.best_pct).toBe(20);
    expect(s.worst_pct).toBe(10);
    expect(s.payoff).toBeNull();                    // no losers yet
  });

  it("pyramiding: 3 open lots on same ticker each priced differently", () => {
    const s = computeStats([
      row({ amount_krw: 1_000_000, entry_price: 100, current_value_krw: 1_100_000 }),
      row({ amount_krw: 1_000_000, entry_price: 110, current_value_krw: 1_055_000 }),
      row({ amount_krw: 1_000_000, entry_price: 120, current_value_krw: 1_015_000 }),
    ]);
    expect(s.open_n).toBe(3);
    expect(s.total_invested_krw).toBe(3_000_000);
    expect(s.total_current_value_krw).toBe(3_170_000);
    expect(s.total_pnl_pct).toBeCloseTo(5.67, 1);
  });
});
