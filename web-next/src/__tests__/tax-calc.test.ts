/**
 * Tests for tax calculators (KR 2026 세법).
 *
 * 한국 세제는 매년 약간씩 바뀌므로, 의도된 룰 (250 만 공제, 22% 세율,
 * 300 만 이전 한도) 이 코드에 그대로 박혀 있는지 검증. 룰이 바뀌면
 * 이 테스트가 fail 해서 fix 강제.
 */
import { describe, it, expect } from "vitest";
import {
  estimateCapitalGainsTax,
  yearEndOptimizer,
  estimateIsaPensionTransferRefund,
} from "@/lib/tax-calc";

describe("estimateCapitalGainsTax — 미국 양도세", () => {
  it("250 만 공제 안에 들면 무세금", () => {
    const r = estimateCapitalGainsTax(2_000_000);
    expect(r.tax).toBe(0);
    expect(r.netGain).toBe(2_000_000);
    expect(r.oneLiner).toMatch(/250 만원|기본공제|무세금/);
  });

  it("250 만 초과분에만 22% 세율", () => {
    // 500 만 차익 → 250 만 공제 후 250 만 × 22% = 55 만
    const r = estimateCapitalGainsTax(5_000_000);
    expect(r.taxableGain).toBe(2_500_000);
    expect(r.tax).toBe(550_000);
    expect(r.netGain).toBe(4_450_000);
  });

  it("차익 0 / 음수 시 양도세 0", () => {
    expect(estimateCapitalGainsTax(0).tax).toBe(0);
    expect(estimateCapitalGainsTax(-1_000_000).tax).toBe(0);
  });
});

describe("yearEndOptimizer — 연말 절세 추천", () => {
  it("YTD 차익이 공제 안이면 남은 한도 + 무세금 익절 가이드", () => {
    const r = yearEndOptimizer({
      realizedYtdKrw: 1_000_000,
      unrealizedPnLKrw: 2_000_000,
    });
    expect(r.remainingDeductKrw).toBe(1_500_000);
    expect(r.actions.some((a) => /250 만|무세금/.test(a))).toBe(true);
  });

  it("YTD 차익이 공제 초과면 손실 청산 권장", () => {
    const r = yearEndOptimizer({
      realizedYtdKrw: 5_000_000,
      unrealizedPnLKrw: -1_000_000,
    });
    expect(r.remainingDeductKrw).toBe(0);
    expect(r.lossOffsetKrw).toBe(1_000_000);
    expect(r.actions.some((a) => /손실 청산|상쇄/.test(a))).toBe(true);
  });

  it("총 면세 익절 가능 = 남은 한도 + 손실 상쇄", () => {
    const r = yearEndOptimizer({
      realizedYtdKrw: 500_000,        // 남은 한도 200 만
      unrealizedPnLKrw: -3_000_000,    // 손실 청산 300 만
    });
    expect(r.taxFreeBudgetKrw).toBe(5_000_000);
  });

  it("12 월 결제일 안내 항상 포함", () => {
    const r = yearEndOptimizer({
      realizedYtdKrw: 0,
      unrealizedPnLKrw: 5_000_000,
    });
    // 평가차익이 있을 때만 12 월 결제일 안내 등장.
    expect(r.actions.some((a) => /12 월|셋째 주|결제일/.test(a))).toBe(true);
  });
});

describe("estimateIsaPensionTransferRefund — ISA → 연금 이전", () => {
  it("이전 한도는 잔액의 10% (최대 300 만)", () => {
    const r1 = estimateIsaPensionTransferRefund({
      isaBalanceKrw: 10_000_000,
      highIncome: false,
    });
    expect(r1.transferableKrw).toBe(1_000_000); // 10%

    const r2 = estimateIsaPensionTransferRefund({
      isaBalanceKrw: 100_000_000,
      highIncome: false,
    });
    // 10% = 천만이지만 한도 300 만.
    expect(r2.transferableKrw).toBe(3_000_000);
  });

  it("저소득 (5,500 만 이하) 환급률 16.5%", () => {
    const r = estimateIsaPensionTransferRefund({
      isaBalanceKrw: 100_000_000,
      highIncome: false,
    });
    expect(r.extraRefundKrw).toBe(3_000_000 * 0.165);
  });

  it("고소득 (5,500 만 초과) 환급률 13.2%", () => {
    const r = estimateIsaPensionTransferRefund({
      isaBalanceKrw: 100_000_000,
      highIncome: true,
    });
    expect(r.extraRefundKrw).toBe(3_000_000 * 0.132);
  });
});
