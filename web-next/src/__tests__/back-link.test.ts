/**
 * Tests for decideBackLink — drives the back-arrow target on
 * /stocks/[ticker]. The page can be entered from /watchlist (back goes
 * there), or from /stocks search, or as a direct hit (no Referer); we
 * want the right destination in each case.
 */
import { describe, it, expect } from "vitest";
import { decideBackLink } from "@/lib/back-link";

describe("decideBackLink", () => {
  it("returns /stocks when there's no Referer (direct hit / new tab)", () => {
    expect(decideBackLink(null)).toEqual({
      href: "/stocks",
      label: "종목 검색",
    });
    expect(decideBackLink(undefined)).toEqual({
      href: "/stocks",
      label: "종목 검색",
    });
    expect(decideBackLink("")).toEqual({
      href: "/stocks",
      label: "종목 검색",
    });
  });

  it("routes back to /watchlist when Referer is the watchlist page", () => {
    expect(
      decideBackLink("https://app.example.com/watchlist"),
    ).toEqual({ href: "/watchlist", label: "관심 종목으로" });
    // Trailing slash + sub-paths still match.
    expect(
      decideBackLink("https://app.example.com/watchlist/"),
    ).toEqual({ href: "/watchlist", label: "관심 종목으로" });
  });

  it("returns /stocks for stock-search and stock-detail Referers", () => {
    // Searching elsewhere → going back means going back to search list.
    expect(
      decideBackLink("https://app.example.com/stocks"),
    ).toEqual({ href: "/stocks", label: "종목 검색" });
    // From another stock detail (e.g. related-link nav) → step out.
    expect(
      decideBackLink("https://app.example.com/stocks/AAPL"),
    ).toEqual({ href: "/stocks", label: "종목 검색" });
  });

  it("falls back to /stocks when Referer is malformed", () => {
    expect(decideBackLink("not-a-url")).toEqual({
      href: "/stocks",
      label: "종목 검색",
    });
    expect(decideBackLink("javascript:alert(1)")).toEqual({
      href: "/stocks",
      // javascript: URLs are parseable as URLs, so the path-based
      // check just doesn't match /watchlist and falls through.
      label: "종목 검색",
    });
  });

  it("does NOT match the substring '/watchlist' inside another path", () => {
    // A hypothetical future page like /admin/watchlist-audit must not
    // hijack the back link.
    expect(
      decideBackLink("https://app.example.com/admin/watchlist-audit"),
    ).toEqual({ href: "/stocks", label: "종목 검색" });
  });

  // Coming from list pages — user expects to go back to the same list
  // (was bug 2026-05-20: /volume-surge → detail → back went to /stocks).
  it("/volume-surge → 거래량 폭증 목록으로", () => {
    expect(decideBackLink("https://app.example.com/volume-surge"))
      .toEqual({ href: "/volume-surge", label: "거래량 폭증 목록으로" });
  });

  it("/flow-ranking → 큰손 매매 랭킹으로", () => {
    expect(decideBackLink("https://app.example.com/flow-ranking"))
      .toEqual({ href: "/flow-ranking", label: "큰손 매매 랭킹으로" });
  });

  it("/screener preserves preset query so user lands on same preset", () => {
    expect(
      decideBackLink("https://app.example.com/screener?preset=value-classic"),
    ).toEqual({
      href: "/screener?preset=value-classic",
      label: "스크리너로",
    });
  });

  it("/screener without query still works", () => {
    expect(decideBackLink("https://app.example.com/screener"))
      .toEqual({ href: "/screener", label: "스크리너로" });
  });
});

// ─────────────────────────────────────────────────────────────────────
// from= URL param tests — preferred over Referer.
// 2026-05-21 regression: Next.js RSC navigation drops/replaces Referer
// for the destination page, so backlink was reverting to "종목 검색".
// Now each list page passes ?from=<source> on its stock link, and that
// param takes priority over Referer.
// ─────────────────────────────────────────────────────────────────────

describe("decideBackLink — ?from= URL param (takes priority over Referer)", () => {
  it("from=screener → 스크리너로 (with optional preset)", () => {
    expect(
      decideBackLink(null, { from: "screener", preset: "value-classic" }),
    ).toEqual({ href: "/screener?preset=value-classic", label: "스크리너로" });

    expect(decideBackLink(null, { from: "screener" }))
      .toEqual({ href: "/screener", label: "스크리너로" });
  });

  it("from=themes → 테마 종목 목록으로 (with theme id)", () => {
    expect(decideBackLink(null, { from: "themes", theme: "12" }))
      .toEqual({ href: "/themes/12", label: "테마 종목 목록으로" });
    // No theme id → /themes list.
    expect(decideBackLink(null, { from: "themes" }))
      .toEqual({ href: "/themes", label: "테마로" });
  });

  it("from=watchlist → 관심 종목으로", () => {
    expect(decideBackLink(null, { from: "watchlist" }))
      .toEqual({ href: "/watchlist", label: "관심 종목으로" });
  });

  it("from=flow-ranking → 큰손 매매 랭킹으로", () => {
    expect(decideBackLink(null, { from: "flow-ranking" }))
      .toEqual({ href: "/flow-ranking", label: "큰손 매매 랭킹으로" });
  });

  it("from=volume-surge → 거래량 폭증 목록으로", () => {
    expect(decideBackLink(null, { from: "volume-surge" }))
      .toEqual({ href: "/volume-surge", label: "거래량 폭증 목록으로" });
  });

  it("from= 가 Referer 보다 우선 — 둘 다 있어도 from= 따름", () => {
    expect(
      decideBackLink("https://app.example.com/watchlist",
        { from: "screener", preset: "value-classic" }),
    ).toEqual({ href: "/screener?preset=value-classic", label: "스크리너로" });
  });

  it("URLSearchParams object 도 받음", () => {
    const sp = new URLSearchParams("from=screener&preset=growth-quality");
    expect(decideBackLink(null, sp))
      .toEqual({ href: "/screener?preset=growth-quality", label: "스크리너로" });
  });

  it("unknown from= 값은 Referer fallback", () => {
    expect(
      decideBackLink("https://app.example.com/watchlist",
        { from: "garbage" }),
    ).toEqual({ href: "/watchlist", label: "관심 종목으로" });
  });
});
