/**
 * Tests for admin-bound Telegram notification formatters.
 *
 * The route handlers fire-and-forget these strings, so the only way a
 * formatting regression surfaces is if a human eyeballs a real
 * notification. These tests are the safety net: HTML escaping, the
 * "<email>" angle-bracket entity encoding (Telegram parser truncates
 * raw '<'), category-label mapping, and body-preview truncation.
 */
import { describe, it, expect } from "vitest";
import {
  formatAccessRequestNotification,
  formatFeedbackNotification,
} from "@/lib/admin-notifications";

describe("formatAccessRequestNotification", () => {
  it("escapes the email's angle brackets so Telegram doesn't truncate", () => {
    const msg = formatAccessRequestNotification(
      "u@example.com",
      "User Name",
      "I'd like access",
    );
    // Brackets MUST appear as entities, never raw.
    expect(msg).toContain("&lt;u@example.com&gt;");
    expect(msg).not.toContain("<u@example.com>");
  });

  it("includes name when given and skips it when absent", () => {
    const withName = formatAccessRequestNotification(
      "u@example.com",
      "John",
      null,
    );
    expect(withName).toMatch(/John &lt;u@example.com&gt;/);

    const noName = formatAccessRequestNotification(
      "u@example.com",
      null,
      null,
    );
    // No leading-space-only fragment before <email>: closing </b> then
    // newline then the bracketed-email entity, no leftover "Name " prefix.
    expect(noName).toMatch(/<\/b>\n&lt;u@example.com&gt;/);
  });

  it("escapes HTML in the reason — defends against tag injection", () => {
    const msg = formatAccessRequestNotification(
      "u@example.com",
      null,
      "<script>alert(1)</script>",
    );
    expect(msg).toContain("&lt;script&gt;alert(1)&lt;/script&gt;");
    expect(msg).not.toContain("<script>");
  });

  it("shows (사유 없음) when reason is null", () => {
    const msg = formatAccessRequestNotification("u@example.com", null, null);
    expect(msg).toContain("(사유 없음)");
  });
});

describe("formatFeedbackNotification", () => {
  it("uses the Korean category label", () => {
    const msg = formatFeedbackNotification({
      id: 7,
      category: "bug",
      title: "차트가 안 보임",
      body: "재현 단계 …",
      userEmail: "u@example.com",
    });
    expect(msg).toContain("🐛 버그 #7");

    const feat = formatFeedbackNotification({
      id: 8,
      category: "feature",
      title: "메모 기능",
      body: "본문",
      userEmail: "u@example.com",
    });
    expect(feat).toContain("💡 건의 #8");
  });

  it("falls back to the raw category if unknown", () => {
    const msg = formatFeedbackNotification({
      id: 9,
      category: "weird",
      title: "t",
      body: "b",
      userEmail: "u@example.com",
    });
    // Unmapped category renders verbatim, ticket # still present.
    expect(msg).toContain("weird #9");
  });

  it("truncates long bodies with ellipsis", () => {
    const longBody = "a".repeat(800);
    const msg = formatFeedbackNotification({
      id: 1,
      category: "bug",
      title: "long",
      body: longBody,
      userEmail: "u@example.com",
    });
    // Preview cap is 600; truncation marker present, full body absent.
    expect(msg).toContain("…");
    expect(msg).not.toContain("a".repeat(800));
    expect(msg).toContain("a".repeat(600));
  });

  it("escapes HTML in the title + body", () => {
    const msg = formatFeedbackNotification({
      id: 2,
      category: "bug",
      title: "<b>buggy</b>",
      body: "<script>xss</script>",
      userEmail: "x@y.com",
    });
    expect(msg).toContain("&lt;b&gt;buggy&lt;/b&gt;");
    expect(msg).toContain("&lt;script&gt;xss&lt;/script&gt;");
    expect(msg).not.toContain("<script>");
  });
});
