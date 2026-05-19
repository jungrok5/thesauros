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
});
