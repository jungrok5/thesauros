/**
 * Tests for news-parsers — both upstream paths.
 *
 *  - Naver Finance 종목뉴스 (KR): table.type5 row layout.
 *  - Google News RSS (US): standard <item> blocks with " - Source" suffix.
 *
 * Real upstream responses can shift cosmetically (Naver A/B tests new
 * markup, Google occasionally rewrites <source> tags); we exercise the
 * regex paths against a fixture that mirrors the current shape so a
 * silent break in either parser fails the suite, not the user.
 */
import { describe, it, expect } from "vitest";
import {
  parseGoogleNewsRss,
  parseNaverNews,
  parseNaverDate,
  stripTags,
} from "@/lib/news-parsers";

describe("parseGoogleNewsRss", () => {
  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Google News</title>
    <item>
      <title>Apple beats Q3 expectations - Reuters</title>
      <link>https://news.google.com/rss/articles/abc123</link>
      <pubDate>Mon, 19 May 2026 14:32:00 GMT</pubDate>
      <source url="https://reuters.com">Reuters</source>
    </item>
    <item>
      <title>Nvidia&apos;s AI moat widens - Bloomberg</title>
      <link>https://news.google.com/rss/articles/def456</link>
      <pubDate>Sun, 18 May 2026 10:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Should not parse — missing link</title>
    </item>
  </channel>
</rss>`;

  it("extracts items, splits source from title, decodes entities", () => {
    const items = parseGoogleNewsRss(xml);
    expect(items).toHaveLength(2);

    // Item 1: dedicated <source> tag.
    expect(items[0].title).toBe("Apple beats Q3 expectations");
    expect(items[0].source).toBe("Reuters");
    expect(items[0].url).toBe("https://news.google.com/rss/articles/abc123");
    expect(items[0].published_at).toBe("2026-05-19T14:32:00.000Z");

    // Item 2: no <source> tag → source inferred from trailing " - X"
    // suffix on the title + apostrophe entity decoded.
    expect(items[1].title).toBe("Nvidia's AI moat widens");
    expect(items[1].source).toBe("Bloomberg");
  });

  it("returns empty array on malformed XML", () => {
    expect(parseGoogleNewsRss("not xml")).toEqual([]);
    expect(parseGoogleNewsRss("")).toEqual([]);
  });
});

describe("parseNaverNews", () => {
  // Pared-down version of the actual table.type5 structure.
  const html = `<table class="type5">
    <tr><th>제목</th><th>정보제공</th><th>날짜</th></tr>
    <tr>
      <td class="title"><a href="/item/news_read.naver?article_id=001">SK하이닉스 4분기 호실적</a></td>
      <td class="info">한국경제</td>
      <td class="date">2026.05.19 14:32</td>
    </tr>
    <tr>
      <td class="title"><a href="https://example.com/abs">절대 URL 외부 기사</a></td>
      <td class="info">조선비즈</td>
      <td class="date">2026.05.18</td>
    </tr>
    <tr><td>더보기</td></tr>
  </table>`;

  it("extracts title/url/source/date, skips header + spacer rows", () => {
    const items = parseNaverNews(html);
    expect(items).toHaveLength(2);
    expect(items[0].title).toBe("SK하이닉스 4분기 호실적");
    expect(items[0].url).toBe(
      "https://finance.naver.com/item/news_read.naver?article_id=001",
    );
    expect(items[0].source).toBe("한국경제");
    expect(items[0].published_at).toBe("2026-05-19T14:32:00+09:00");

    // Absolute URLs stay absolute.
    expect(items[1].url).toBe("https://example.com/abs");
    // Date-only rows still parse to midnight KST.
    expect(items[1].published_at).toBe("2026-05-18T00:00:00+09:00");
  });
});

describe("parseNaverDate", () => {
  it("handles full datetime and date-only forms", () => {
    expect(parseNaverDate("2026.05.19 14:32")).toBe(
      "2026-05-19T14:32:00+09:00",
    );
    expect(parseNaverDate("2026.05.19")).toBe(
      "2026-05-19T00:00:00+09:00",
    );
    expect(parseNaverDate("bogus")).toBeNull();
  });
});

describe("stripTags", () => {
  it("removes tags and decodes named + numeric entities", () => {
    expect(stripTags("<b>Hello</b> &amp; world")).toBe("Hello & world");
    expect(stripTags("&#39;quote&#39;")).toBe("'quote'");
    expect(stripTags("&#x2014;")).toBe("—");
  });
});
