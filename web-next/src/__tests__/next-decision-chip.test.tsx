/**
 * Tests for the "다음 매매 결정 D-x" chip.
 *
 * Background — book 2부 3장 : "주봉 = 매주 금요일 오후 2시 1회 확인".
 * The chip's job is to make that cadence visible on every decision-
 * surface page so the user doesn't open the app daily out of habit.
 * Regression boundary: the next-decision math (next Friday 15:30 KST)
 * must NOT drift on a given clock — that's what makes the chip
 * trustworthy.
 */
import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { NextDecisionChip } from "@/components/next-decision-chip";

afterEach(cleanup);

// Helper — render at a specific UTC instant by stubbing Date().
function renderAt(utcIso: string) {
  vi.useFakeTimers();
  vi.setSystemTime(new Date(utcIso));
}

afterEach(() => {
  vi.useRealTimers();
});


describe("NextDecisionChip — when 'next decision' is", () => {
  it("Friday 09:00 KST → 오늘 (decision is today's close)", () => {
    // 2026-05-22 (Fri) 00:00 UTC = 09:00 KST.
    renderAt("2026-05-22T00:00:00Z");
    const { container } = render(<NextDecisionChip />);
    expect(container.textContent).toMatch(/오늘/);
  });

  it("Friday 15:00 KST → 오늘 (still before 15:30 cutoff)", () => {
    renderAt("2026-05-22T06:00:00Z");  // 06 UTC = 15 KST
    const { container } = render(<NextDecisionChip />);
    expect(container.textContent).toMatch(/오늘/);
  });

  it("Friday 16:00 KST → D-6 (today's close already settled, next Friday 15:30 → ~6d23h)", () => {
    renderAt("2026-05-22T07:00:00Z");  // 07 UTC = 16 KST
    const { container } = render(<NextDecisionChip />);
    expect(container.textContent).toMatch(/D-6/);
  });

  it("Saturday 10:00 KST → D-6", () => {
    renderAt("2026-05-23T01:00:00Z");  // 01 UTC = 10 KST Sat
    const { container } = render(<NextDecisionChip />);
    expect(container.textContent).toMatch(/D-6/);
  });

  it("Sunday → D-5", () => {
    renderAt("2026-05-24T01:00:00Z");  // Sun
    const { container } = render(<NextDecisionChip />);
    expect(container.textContent).toMatch(/D-5/);
  });

  it("Monday → D-4", () => {
    renderAt("2026-05-25T01:00:00Z");
    const { container } = render(<NextDecisionChip />);
    expect(container.textContent).toMatch(/D-4/);
  });

  it("Thursday → 내일", () => {
    renderAt("2026-05-28T01:00:00Z");  // Thu 10 KST
    const { container } = render(<NextDecisionChip />);
    expect(container.textContent).toMatch(/내일/);
  });
});


describe("NextDecisionChip — content invariants", () => {
  beforeEach(() => {
    renderAt("2026-05-25T01:00:00Z");  // Monday
  });

  it("default variant mentions 15:30 KST anchor (the book's decision time)", () => {
    const { container } = render(<NextDecisionChip />);
    expect(container.textContent).toMatch(/15:30 KST/);
  });

  it("default variant references the book spirit", () => {
    const { container } = render(<NextDecisionChip />);
    expect(container.textContent).toMatch(/책 정신/);
  });

  it("compact variant is short — no book-spirit explainer", () => {
    const { container } = render(<NextDecisionChip compact />);
    expect(container.textContent).not.toMatch(/책 정신/);
    // But the headline countdown must still be visible.
    expect(container.textContent).toMatch(/다음 결정/);
  });
});
