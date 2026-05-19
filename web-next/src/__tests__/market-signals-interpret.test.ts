/**
 * Tests for market-signal interpreters.
 *
 * Each helper returns a SignalCard the UI renders — tone (color),
 * one-liner, scenarios, actions. Tests pin:
 *
 *   1. Tone matches severity. A 거래정지 must be tone:"bad"; a normal
 *      short balance must be tone:"good".
 *   2. Action text contains specific dates from the input when given
 *      (the user's "날짜까지 알 수 있다면 포함" requirement).
 *   3. Easy/plain Korean wording — no English jargon leaks.
 *   4. Halloween dates flip on the right boundary.
 */
import { describe, it, expect } from "vitest";
import {
  interpretMarketWarnings,
  interpretShortSales,
  interpretDividend,
  interpretSeasonal,
} from "@/lib/market-signals-interpret";

describe("interpretMarketWarnings", () => {
  it("returns null when there are no warnings", () => {
    expect(interpretMarketWarnings([])).toBe(null);
  });

  it("trading_halt → bad tone + specific expiry date in action", () => {
    const card = interpretMarketWarnings([
      {
        level: "trading_halt",
        reason: "회계감리",
        designated_at: "2026-05-10",
        expires_at: "2026-06-03",
      },
    ])!;
    expect(card.tone).toBe("bad");
    expect(card.label).toContain("거래정지");
    // Date range in one-liner.
    expect(card.oneLiner).toContain("2026-05-10");
    expect(card.oneLiner).toContain("2026-06-03");
    // Specific expiry date repeated in action prescription.
    expect(card.actions.join(" ")).toContain("2026-06-03");
  });

  it("surveillance gives recovery + escalation scenarios", () => {
    const card = interpretMarketWarnings([
      { level: "surveillance", reason: null, designated_at: null, expires_at: null },
    ])!;
    expect(card.tone).toBe("bad");
    expect(card.scenarios?.length).toBe(2);
    expect(card.scenarios?.[0].tag).toMatch(/회복/);
    expect(card.scenarios?.[1].tag).toMatch(/악화/);
  });

  it("picks the worst level when multiple warnings stack", () => {
    const card = interpretMarketWarnings([
      { level: "overheat", reason: null, designated_at: null, expires_at: null },
      { level: "warning", reason: null, designated_at: null, expires_at: null },
      { level: "risk", reason: null, designated_at: null, expires_at: null },
    ])!;
    expect(card.label).toContain("투자위험");
  });

  it("overheat → neutral tone", () => {
    const card = interpretMarketWarnings([
      { level: "overheat", reason: null, designated_at: null, expires_at: null },
    ])!;
    expect(card.tone).toBe("neutral");
  });

  it("uses plain Korean — no English jargon in surveillance card", () => {
    const card = interpretMarketWarnings([
      { level: "surveillance", reason: null, designated_at: null, expires_at: null },
    ])!;
    const text = [
      card.oneLiner,
      ...card.actions,
      ...(card.scenarios?.map((s) => s.body) ?? []),
    ].join(" ");
    // Specific jargon we explicitly avoided.
    expect(text).not.toMatch(/\bstretch\b/i);
    expect(text).not.toMatch(/\bcatalyst\b/i);
    expect(text).not.toMatch(/\btrailing stop\b/i);
    expect(text).not.toMatch(/\bsqueeze\b/i);
  });
});

describe("interpretShortSales", () => {
  it("balance ≥ 5% → warn tone + scenarios", () => {
    const card = interpretShortSales({
      latestDay: "2026-05-18",
      balanceRatio: 0.062,
      todayRatio: 0.05,
      fiveDayAvgRatio: 0.04,
    })!;
    expect(card.tone).toBe("warn");
    expect(card.oneLiner).toContain("6.20%");
    expect(card.scenarios?.length).toBe(2);
    expect(card.scenarios?.some((s) => /숏커버링|급반등/.test(s.tag))).toBe(true);
    // Date in one-liner.
    expect(card.oneLiner).toContain("2026-05-18");
  });

  it("balance 3-5% → neutral with growth flag when accelerating", () => {
    const card = interpretShortSales({
      latestDay: "2026-05-18",
      balanceRatio: 0.04,
      todayRatio: 0.10,
      fiveDayAvgRatio: 0.05,
    })!;
    expect(card.tone).toBe("neutral");
    // Plain-Korean "급증" or "빠르게 증가" both qualify as the
    // acceleration callout we promise.
    expect(card.oneLiner).toMatch(/급증|빠르게 증가/);
  });

  it("normal levels → good tone", () => {
    const card = interpretShortSales({
      latestDay: "2026-05-18",
      balanceRatio: 0.012,
      todayRatio: 0.05,
      fiveDayAvgRatio: 0.04,
    })!;
    expect(card.tone).toBe("good");
  });

  it("returns null when both ratios are missing", () => {
    expect(
      interpretShortSales({
        latestDay: null,
        balanceRatio: null,
        todayRatio: null,
        fiveDayAvgRatio: null,
      }),
    ).toBe(null);
  });
});

describe("interpretDividend", () => {
  it("ex_dividend in 3 days → warn + concrete last-buy date", () => {
    const card = interpretDividend({
      exDividend: "2026-05-22",
      recordDate: "2026-05-23",
      paymentDate: "2026-06-15",
      dps: 500,
      yieldPct: 4.5,
      todayIso: "2026-05-19",
    })!;
    expect(card.tone).toBe("warn");
    // Last buy day = ex_dividend - 1 = 2026-05-21
    expect(card.oneLiner).toContain("2026-05-21");
    expect(card.oneLiner).toContain("D-3");
    expect(card.oneLiner).toContain("4.50%");
    expect(card.oneLiner).toContain("500원");
  });

  it("ex_dividend in the past → neutral 'next batting' framing", () => {
    const card = interpretDividend({
      exDividend: "2026-03-29",
      recordDate: null,
      paymentDate: null,
      dps: 500,
      yieldPct: 3.5,
      todayIso: "2026-05-19",
    })!;
    expect(card.tone).toBe("neutral");
    // Header label flags this as the post-batting state.
    expect(card.label).toContain("종료");
    expect(card.oneLiner).toContain("직전 배당락");
  });

  it("high yield without imminent date → good", () => {
    const card = interpretDividend({
      exDividend: null,
      recordDate: null,
      paymentDate: null,
      dps: 1000,
      yieldPct: 5.5,
      todayIso: "2026-05-19",
    })!;
    expect(card.tone).toBe("good");
    expect(card.label).toContain("고배당");
  });

  it("returns null when no dividend data at all", () => {
    expect(
      interpretDividend({
        exDividend: null,
        recordDate: null,
        paymentDate: null,
        dps: null,
        yieldPct: null,
        todayIso: "2026-05-19",
      }),
    ).toBe(null);
  });
});

describe("interpretSeasonal (Halloween effect)", () => {
  it("January = bullish window, mentions next transition (May 1)", () => {
    const card = interpretSeasonal({ todayIso: "2026-01-15" });
    expect(card.tone).toBe("good");
    expect(card.label).toContain("강세");
    expect(card.oneLiner).toContain("2026-05-01");
  });

  it("July = bearish window, mentions next transition (Nov 1)", () => {
    const card = interpretSeasonal({ todayIso: "2026-07-15" });
    expect(card.tone).toBe("neutral");
    expect(card.label).toContain("약세");
    expect(card.oneLiner).toContain("2026-11-01");
  });

  it("November transitions to bullish", () => {
    const card = interpretSeasonal({ todayIso: "2026-11-01" });
    expect(card.tone).toBe("good");
  });

  it("April still bullish; May 1 is the flip", () => {
    expect(interpretSeasonal({ todayIso: "2026-04-30" }).tone).toBe("good");
    expect(interpretSeasonal({ todayIso: "2026-05-01" }).tone).toBe("neutral");
  });

  it("December includes the year-end dividend record date callout", () => {
    const card = interpretSeasonal({ todayIso: "2026-12-15" });
    const text = card.actions.join(" ");
    expect(text).toMatch(/12월 말|연말 배당/);
  });
});
