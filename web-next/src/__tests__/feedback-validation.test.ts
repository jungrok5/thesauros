/**
 * Tests for parseFeedbackInput — guards the /api/feedback POST contract.
 *
 * A loose validator here would let buggy clients pollute the DB with
 * blank titles, unknown categories, or 1MB bodies. Each branch in the
 * route handler that maps to a 400 should have a covering test.
 */
import { describe, it, expect } from "vitest";
import {
  parseFeedbackInput,
  FEEDBACK_TITLE_MAX,
  FEEDBACK_BODY_MAX,
} from "@/lib/feedback-validation";

describe("parseFeedbackInput", () => {
  it("accepts a well-formed bug report", () => {
    const r = parseFeedbackInput({
      category: "bug",
      title: "차트 깨짐",
      body: "재현 단계: …",
      page_url: "/stocks/AAPL",
    });
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.category).toBe("bug");
      expect(r.title).toBe("차트 깨짐");
      expect(r.body).toBe("재현 단계: …");
      expect(r.pageUrl).toBe("/stocks/AAPL");
    }
  });

  it("rejects unknown categories", () => {
    const r = parseFeedbackInput({
      category: "spam",
      title: "x",
      body: "y",
    });
    expect(r).toEqual({ ok: false, error: "invalid category" });
  });

  it("rejects empty title or body even when trimmed whitespace", () => {
    expect(parseFeedbackInput({ category: "bug", title: "", body: "x" })).toEqual({
      ok: false,
      error: "missing title or body",
    });
    expect(
      parseFeedbackInput({ category: "bug", title: "   ", body: "x" }),
    ).toEqual({ ok: false, error: "missing title or body" });
    expect(parseFeedbackInput({ category: "bug", title: "x", body: "" })).toEqual({
      ok: false,
      error: "missing title or body",
    });
  });

  it("clips over-length title and body to the documented maxes", () => {
    const r = parseFeedbackInput({
      category: "other",
      title: "x".repeat(FEEDBACK_TITLE_MAX + 100),
      body: "y".repeat(FEEDBACK_BODY_MAX + 1000),
    });
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.title.length).toBe(FEEDBACK_TITLE_MAX);
      expect(r.body.length).toBe(FEEDBACK_BODY_MAX);
    }
  });

  it("normalizes page_url null when missing or non-string", () => {
    const a = parseFeedbackInput({ category: "bug", title: "x", body: "y" });
    expect(a.ok && a.pageUrl).toBe(null);

    const b = parseFeedbackInput({
      category: "bug",
      title: "x",
      body: "y",
      page_url: null,
    });
    expect(b.ok && b.pageUrl).toBe(null);
  });

  it("rejects non-object bodies", () => {
    expect(parseFeedbackInput(null).ok).toBe(false);
    expect(parseFeedbackInput("string").ok).toBe(false);
    expect(parseFeedbackInput(42).ok).toBe(false);
  });
});
