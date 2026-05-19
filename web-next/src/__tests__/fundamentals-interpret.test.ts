/**
 * Tests for the financials + factors interpreters.
 *
 * These power the "한 줄 평 + 도출" cards on /stocks/[ticker]. We test
 * the rule branches that decide tone (good/neutral/warn/bad), the
 * takeaway phrasing for representative inputs (high growth, recession,
 * over-levered, etc.), and the fallback behavior when key inputs are
 * null (no PER → "미산정" message, not a crash).
 */
import { describe, it, expect } from "vitest";
import {
  interpretFinancials,
  interpretFactors,
} from "@/lib/fundamentals-interpret";
import type {
  FinancialsEvalRow,
  FactorsEvalRow,
} from "@/lib/supabase";

function fin(overrides: Partial<FinancialsEvalRow> = {}): FinancialsEvalRow {
  return {
    ticker: "TEST",
    revenue_3y: null,
    operating_income_3y: null,
    net_income_3y: null,
    assets_3y: null,
    debt_3y: null,
    equity_3y: null,
    debt_ratio: null,
    roe: null,
    roa: null,
    op_margin: null,
    revenue_growth_yoy: null,
    net_income_growth_yoy: null,
    current_ratio: null,
    f_score: null,
    rules_eval: null,
    composite_score: null,
    summary_text: null,
    updated_at: "2026-05-19T00:00:00Z",
    ...overrides,
  };
}

function fac(overrides: Partial<FactorsEvalRow> = {}): FactorsEvalRow {
  return {
    ticker: "TEST",
    per: null, per_pctile: null, per_eval: null,
    pbr: null, pbr_pctile: null, pbr_eval: null,
    roe: null, roe_pctile: null, roe_eval: null,
    roa: null, roa_pctile: null, roa_eval: null,
    op_margin: null, op_margin_pctile: null, op_margin_eval: null,
    debt_ratio: null, debt_ratio_pctile: null, debt_ratio_eval: null,
    revenue_growth: null, revenue_growth_pctile: null,
    passes_kang_value: null,
    passes_graham: null,
    passes_magic_formula: null,
    passes_buffett: null,
    value_score: null,
    growth_score: null,
    safety_score: null,
    quality_score: null,
    summary_text: null,
    updated_at: "2026-05-19T00:00:00Z",
    ...overrides,
  };
}

describe("interpretFinancials", () => {
  it("rates a high-growth, profitable, safe company as good", () => {
    const r = interpretFinancials(
      fin({
        revenue_growth_yoy: 0.25,
        roe: 0.20,
        op_margin: 0.18,
        debt_ratio: 0.35,
      }),
    );
    expect(r.tone).toBe("good");
    expect(r.label).toBe("🟢 우수");
    expect(r.oneLiner).toContain("성장 견조");
    expect(r.oneLiner).toContain("수익성 우수");
    expect(r.takeaways.join(" ")).toMatch(/고성장|매수 자격/);
  });

  it("rates over-levered profitable as warn or bad (safety counts double)", () => {
    const r = interpretFinancials(
      fin({
        revenue_growth_yoy: 0.15,
        roe: 0.18,
        op_margin: 0.20,
        debt_ratio: 1.5,        // over-levered
      }),
    );
    // Safety -1 (×2) + profit +1 + growth +1 = 0 → warn
    expect(["warn", "bad"]).toContain(r.tone);
    expect(r.takeaways.join(" ")).toMatch(/부채.*과도|자본 보전/);
  });

  it("rates loss-making, over-levered company as bad", () => {
    const r = interpretFinancials(
      fin({
        revenue_growth_yoy: -0.10,
        roe: -0.05,
        op_margin: -0.02,
        debt_ratio: 1.2,
      }),
    );
    expect(r.tone).toBe("bad");
    expect(r.oneLiner).toContain("역성장");
    expect(r.takeaways.join(" ")).toMatch(/적자|recovery|매수 후보 X/);
  });

  it("returns a 'data insufficient' message when all inputs are null", () => {
    const r = interpretFinancials(fin());
    // All inputs null → aggregate 0 → neutral, but oneLiner falls back.
    expect(r.oneLiner).toContain("지표 부족");
    expect(r.takeaways).toEqual([]);
  });

  it("treats negative growth + good profit as neutral, not good", () => {
    const r = interpretFinancials(
      fin({
        revenue_growth_yoy: -0.05,
        roe: 0.18,
        op_margin: 0.15,
        debt_ratio: 0.30,
      }),
    );
    // growth -1, profit +1, safety +1 (×2) = +2 → neutral
    expect(r.tone).toBe("neutral");
  });
});

describe("interpretFactors", () => {
  it("rates 3+ gates passed as good", () => {
    const r = interpretFactors(
      fac({
        per: 8, pbr: 1.0, roe: 0.18,
        passes_kang_value: true,
        passes_graham: true,
        passes_magic_formula: true,
        passes_buffett: true,
        value_score: 8, growth_score: 7, safety_score: 8, quality_score: 9,
      }),
    );
    expect(r.tone).toBe("good");
    expect(r.oneLiner).toContain("4/4 통과");
    expect(r.takeaways.join(" ")).toMatch(/4\/4 통과|매수 후보/);
  });

  it("rates 0 gates + low total as bad", () => {
    const r = interpretFactors(
      fac({
        per: 50, pbr: 8,
        passes_kang_value: false,
        passes_graham: false,
        passes_magic_formula: false,
        passes_buffett: false,
        value_score: 1, growth_score: 2, safety_score: 2, quality_score: 3,
      }),
    );
    // 0 gates + total 8 → bad
    expect(r.tone).toBe("bad");
    expect(r.oneLiner).toContain("0/4 통과");
  });

  it("surfaces the 미산정 message when PER/PBR are null", () => {
    const r = interpretFactors(
      fac({
        per: null, pbr: null,
        passes_buffett: true,
        passes_kang_value: false,
        passes_graham: false,
        passes_magic_formula: false,
        value_score: 0, growth_score: 5, safety_score: 6, quality_score: 6,
      }),
    );
    expect(r.takeaways.join(" ")).toMatch(/미산정|시가총액/);
  });

  it("calls out partial gate pass with the passing screen's name", () => {
    const r = interpretFactors(
      fac({
        per: 10, pbr: 1.2, roe: 0.18,
        passes_kang_value: true,
        passes_graham: false,
        passes_magic_formula: false,
        passes_buffett: true,
        value_score: 5, growth_score: 4, safety_score: 6, quality_score: 7,
      }),
    );
    expect(r.takeaways.join(" ")).toMatch(/강환국/);
    expect(r.takeaways.join(" ")).toMatch(/버핏/);
  });

  it("counts gates against evaluable total, not just passed/null", () => {
    // 1 of 2 evaluable gates pass; rest are null → not in denominator
    const r = interpretFactors(
      fac({
        per: 10,
        passes_kang_value: true,
        passes_graham: false,
        passes_magic_formula: null,
        passes_buffett: null,
        value_score: 5, growth_score: 5, safety_score: 5, quality_score: 5,
      }),
    );
    // gatesPassed=1, gatesEvaluable=2 → "1/2 통과" in oneLiner
    expect(r.oneLiner).toContain("1/2");
  });
});
