/**
 * Tests for macro indicator interpreters.
 *
 * The dashboard renders a 한 줄 hint per indicator so users don't have
 * to translate raw numbers (CPI 3.4%, 10Y 4.2%, etc.) into "what should
 * I do about it". We test:
 *
 *   1. tickerHint(): static rules only — equity/index symbols get null
 *      (no tautology), VIX/금리/원유/금/달러 get a one-line directional
 *      rule.
 *
 *   2. indicatorVerdict(): static impact line + state-driven action.
 *      We check the major indicator families (CPI, rate, yield curve,
 *      HY spread, VIX) for each state.
 */
import { describe, it, expect } from "vitest";
import { tickerHint, indicatorVerdict } from "@/lib/macro-interpret";

describe("tickerHint", () => {
  it("returns null for stock indices (tautological)", () => {
    expect(tickerHint("^KS11")).toBe(null);
    expect(tickerHint("^GSPC")).toBe(null);
    expect(tickerHint("^IXIC")).toBe(null);
    expect(tickerHint("^DJI")).toBe(null);
  });

  it("returns a directional rule for VIX", () => {
    const hint = tickerHint("^VIX")!;
    expect(hint).toContain("공포");
    expect(hint).toContain("주식");
  });

  it("FX (USD/KRW), 10Y, oil, gold, BTC all get hints", () => {
    expect(tickerHint("KRW=X")).toContain("수출주");
    expect(tickerHint("^TNX")).toContain("성장주");
    expect(tickerHint("CL=F")).toContain("에너지주");
    expect(tickerHint("GC=F")).toContain("위험 회피");
    expect(tickerHint("BTC-USD")).toContain("위험자산");
  });

  it("unknown symbols return null gracefully", () => {
    expect(tickerHint("UNKNOWN")).toBe(null);
    expect(tickerHint("")).toBe(null);
  });
});

describe("indicatorVerdict", () => {
  it("CPI: state drives the action wording", () => {
    const bull = indicatorVerdict("cpi", "BULL", 2.3, null);
    expect(bull.tone).toBe("good");
    expect(bull.impact).toContain("인플레");
    expect(bull.action).toMatch(/인플레 진정|금리 인하/);

    const bear = indicatorVerdict("cpi", "BEAR", 5.1, null);
    expect(bear.tone).toBe("bad");
    expect(bear.action).toMatch(/매파|비중 축소/);
  });

  it("yield curve: detects inversion (negative value) in NEUTRAL", () => {
    const inv = indicatorVerdict("yield_curve_10y_2y", "NEUTRAL", -0.5, null);
    expect(inv.action).toMatch(/역전 지속/);

    const recovering = indicatorVerdict("yield_curve_10y_2y", "NEUTRAL", 0.2, null);
    expect(recovering.action).toMatch(/역전 회복/);
  });

  it("HY credit spread: stress vs normal", () => {
    const stress = indicatorVerdict("credit_spread_hy", "BEAR", 7.2, null);
    expect(stress.tone).toBe("bad");
    expect(stress.action).toMatch(/현금|침체/);

    const normal = indicatorVerdict("credit_spread_hy", "BULL", 3.1, null);
    expect(normal.tone).toBe("good");
    expect(normal.action).toMatch(/risk-on|주식 매수 우호/);
  });

  it("VIX: states map to clear panic levels", () => {
    const calm = indicatorVerdict("vix", "BULL", 15, null);
    expect(calm.action).toContain("매수 자리");

    const panic = indicatorVerdict("vix", "BEAR", 35, null);
    expect(panic.action).toContain("자본 보전");
  });

  it("real rate 10Y: 2%+ flagged as heavy-debt pressure", () => {
    const heavy = indicatorVerdict("real_rate_10y", "CAUTION", 2.1, null);
    expect(heavy.tone).toBe("warn");
    // Plain-Korean phrasing — 빚 많은 회사 / 신생 기업.
    expect(heavy.action).toMatch(/빚 많은|신생/);
  });

  it("DXY: KR/EM sensitivity flagged correctly", () => {
    const krFavorable = indicatorVerdict("dxy", "BULL", 99, null);
    expect(krFavorable.action).toMatch(/코스피|신흥국/);

    const strong = indicatorVerdict("dxy", "BEAR", 110, null);
    expect(strong.action).toMatch(/위험 회피|폭등/);
  });

  it("unknown key falls through to a sane default verdict", () => {
    const r = indicatorVerdict("totally_made_up", "NEUTRAL", 0, null);
    expect(r.action).toBeTruthy();
    expect(r.impact).toBeTruthy();
    expect(r.tone).toBe("neutral");
  });

  // 2026-05-29 — krEconomy (국내 경제 영향) line for the indicators
  // users explicitly asked to understand: 미국 금리 / 한국 금리 / 환율 / 금.
  // Pins that the verdict carries the plain-Korean KR economy note so
  // the dashboard card can render the 🇰🇷 line.
  describe("krEconomy (국내 경제 한 줄)", () => {
    it("fed_funds_rate carries KR rate follow-on", () => {
      const v = indicatorVerdict("fed_funds_rate", "CAUTION", 5.5, null);
      expect(v.krEconomy).toBeTruthy();
      // Should explain that KR base rate tracks US rate.
      expect(v.krEconomy).toMatch(/한국은행|한국 금리|대출이자/);
    });

    it("real_rate_10y carries foreign-fund-flow + FX note", () => {
      const v = indicatorVerdict("real_rate_10y", "CAUTION", 2.2, null);
      expect(v.krEconomy).toBeTruthy();
      expect(v.krEconomy).toMatch(/외국인|환율/);
    });

    it("dxy carries USD/KRW + import-price note", () => {
      const v = indicatorVerdict("dxy", "CAUTION", 106, null);
      expect(v.krEconomy).toBeTruthy();
      expect(v.krEconomy).toMatch(/원\/달러|수입|환율/);
    });

    it("usdkrw key carries beginner-friendly export/import note", () => {
      const v = indicatorVerdict("usdkrw", "CAUTION", 1410, null);
      expect(v.krEconomy).toBeTruthy();
      expect(v.krEconomy).toMatch(/수입|수출|물가/);
    });

    it("gold carries inflation-hedge / KR risk-off note", () => {
      const v = indicatorVerdict("gold", "BULL", 2400, null);
      expect(v.krEconomy).toBeTruthy();
      expect(v.krEconomy).toMatch(/인플레|헷지|risk-off/i);
    });

    it("usdjpy carries KR vs JP export competitiveness note", () => {
      const v = indicatorVerdict("usdjpy", "CAUTION", 155, null);
      expect(v.krEconomy).toBeTruthy();
      // KR-JP overlap industries (auto, shipbuilding) mentioned in action;
      // krEconomy focuses on consumer-side ripple.
      expect(v.krEconomy).toMatch(/일본|관광|소비/);
    });

    it("indicators outside the curated set have no krEconomy", () => {
      // CPI / yield curve / VIX etc. don't get the KR economy line —
      // their primary story is global, not KR-specific.
      expect(indicatorVerdict("cpi", "BULL", 2, null).krEconomy).toBeUndefined();
      expect(indicatorVerdict("vix", "BULL", 15, null).krEconomy).toBeUndefined();
      expect(indicatorVerdict("yield_curve_10y_2y", "BULL", 0.5, null).krEconomy).toBeUndefined();
    });
  });
});
