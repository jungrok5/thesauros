/**
 * Investor-intel action-line logic — the bucket boundaries determine
 * which sentence the user reads under each card. Tests lock the
 * thresholds so a future "tweak the copy" doesn't silently move where
 * the bucket cuts (e.g. "30% 저평가" vs "조금 더 오를 여지").
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import {
  consensusActionLine,
  holdersActionLine,
  earningsActionLine,
  daysFromToday,
} from "@/lib/investor-intel-actions";
import type { InstitutionalOwnershipRow } from "@/lib/stock-context";

describe("consensusActionLine", () => {
  it("returns the catch-all when no target_price or last_close", () => {
    expect(consensusActionLine(null, 100)).toContain("참고용");
    expect(consensusActionLine(150, null)).toContain("참고용");
    expect(consensusActionLine(150, 0)).toContain("참고용");
  });

  it("upside > 30% → 저평가 bucket", () => {
    const out = consensusActionLine(200, 100);   // +100% upside
    expect(out).toContain("저평가");
  });

  it("upside 0-30% → 조금 더 오를 여지 bucket", () => {
    const out = consensusActionLine(120, 100);   // +20%
    expect(out).toContain("조금 더 오를 여지");
  });

  it("upside 0 to -10% → 차익실현 자리 bucket", () => {
    const out = consensusActionLine(95, 100);    // -5%
    expect(out).toContain("차익실현");
  });

  it("upside < -10% → 추격 신중 bucket", () => {
    const out = consensusActionLine(80, 100);    // -20%
    expect(out).toContain("추격은 신중");
  });
});

describe("holdersActionLine", () => {
  function row(
    name: string,
    type: InstitutionalOwnershipRow["holder_type"],
    pct: number,
  ): InstitutionalOwnershipRow {
    return {
      holder_name: name,
      holder_type: type,
      shares: 0,
      share_pct: pct,
      reported_date: "2026-05-01",
    };
  }

  it("NPS + external ≥ 20% → 매물 부담 작은 종목 message", () => {
    const rows = [row("국민연금공단", "NPS", 12), row("미래에셋", "AMC", 10)];
    const out = holdersActionLine(rows);
    expect(out).toContain("폭락장에서도");
  });

  it("NPS alone (low pct) → 안전 후보 bucket", () => {
    const rows = [row("국민연금공단", "NPS", 7)];
    const out = holdersActionLine(rows);
    expect(out).toContain("안전 후보");
  });

  it("AFFILIATE-only (cross-holding) → 모멘텀 약함 bucket", () => {
    // The Samsung-style case: 삼성물산 holds 19.7% of 삼성전자 + no
    // real external 큰손. Before the AFFILIATE bucket existed this
    // mis-counted as "외부 큰손 30%" and gave a misleading message.
    const rows = [row("삼성물산", "AFFILIATE", 25)];
    const out = holdersActionLine(rows);
    expect(out).toContain("그룹 계열사");
    expect(out).toContain("모멘텀");
  });

  it("AFFILIATE does NOT inflate the external 30% threshold", () => {
    // 25% affiliate + 8% AMC = 33% total — but external only 8% so
    // shouldn't hit the "외부 큰손 30%↑" volatility warning.
    const rows = [
      row("삼성물산", "AFFILIATE", 25),
      row("미래에셋", "AMC", 8),
    ];
    const out = holdersActionLine(rows);
    expect(out).not.toContain("변동성 크고");
  });

  it("no NPS but EXTERNAL ≥ 30% → 유통주식 부족 bucket", () => {
    const rows = [
      row("미래에셋", "AMC", 20),
      row("한국투자", "AMC", 12),
    ];
    const out = holdersActionLine(rows);
    expect(out).toContain("변동성 크고");
  });

  it("low everything → fallback line", () => {
    const out = holdersActionLine([row("X", "OTHER", 6)]);
    expect(out).toContain("자금 흐름이 단단");
  });

  it("empty list → fallback (no crash)", () => {
    expect(holdersActionLine([])).toContain("자금 흐름");
  });
});

describe("earningsActionLine", () => {
  it("0-14 days → 새 진입 미루기 bucket", () => {
    expect(earningsActionLine(7)).toContain("발표일까지");
    expect(earningsActionLine(0)).toContain("발표일까지");
    expect(earningsActionLine(14)).toContain("발표일까지");
  });

  it("15-45 days → 미리 비중 조절 bucket", () => {
    expect(earningsActionLine(30)).toContain("일 뒤 발표");
    expect(earningsActionLine(45)).toContain("일 뒤 발표");
  });

  it("> 45 days → generic message", () => {
    expect(earningsActionLine(60)).toContain("추세 안 잡힌");
  });

  it("past (negative days) → generic message", () => {
    expect(earningsActionLine(-5)).toContain("추세 안 잡힌");
  });
});

describe("daysFromToday", () => {
  // Freeze "now" to a UTC midnight so the math is deterministic.
  afterEach(() => vi.useRealTimers());

  it("returns positive for future dates", () => {
    const now = new Date("2026-05-20T00:00:00Z");
    expect(daysFromToday("2026-05-25", now)).toBe(5);
    expect(daysFromToday("2026-06-19", now)).toBe(30);
  });

  it("returns 0 at exactly midnight UTC of the same day", () => {
    const now = new Date("2026-05-20T00:00:00Z");
    expect(daysFromToday("2026-05-20", now)).toBe(0);
  });

  it("returns negative for past dates", () => {
    const now = new Date("2026-05-20T00:00:00Z");
    expect(daysFromToday("2026-05-15", now)).toBe(-5);
  });
});
