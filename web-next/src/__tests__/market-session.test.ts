/**
 * Regression battery for market-session classification — the bug class
 * that has been re-introduced 3 times:
 *   4956455 fix(book): honor 종가매매 — close-only labels + 15:30 cutoffs
 *   0d7d926 fix(quote): 실시간 종가 + 잘못된 날짜 표시 제거
 *   ae076ef test(features): 종가 미래 날짜 (5월 22일) 버그 fix
 * Now (2026-05-21): user reports yet again — "장중인데 최종 종가 라고
 * 표시됨".
 *
 * This suite locks down the classification at every cutoff edge so any
 * future regression fails CI loudly.
 */
import { describe, it, expect } from "vitest";
import { classifySession, priceLabelFor } from "@/lib/market-session";

/** Build a Date that represents `YYYY-MM-DDTHH:MM` in the given IANA
 *  timezone. Used to inject `now` into classifySession with confidence.
 *  Works by computing the offset for that specific moment in that tz. */
function makeDateAt(
  isoLocal: string,    // "2026-05-21T11:00"
  tz: string,          // "Asia/Seoul"
): Date {
  // First guess: treat as UTC.
  const guess = new Date(`${isoLocal}:00.000Z`);
  // Format that UTC instant back in the target tz to see the offset.
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    hour12: false,
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit",
  }).formatToParts(guess);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  const tzWall = `${get("year")}-${get("month")}-${get("day")}T${get("hour")}:${get("minute")}`;
  // Difference between intended local wall-clock and what tz showed.
  const intended = new Date(`${isoLocal}:00.000Z`).getTime();
  const shown = new Date(`${tzWall}:00.000Z`).getTime();
  // Adjust by the difference to get the right UTC instant.
  return new Date(guess.getTime() + (intended - shown));
}

describe("market-session.classifySession — KR ticker", () => {
  const TICKER = "068930.KQ";

  it("Wed 11:00 KST, asOf=today → intraday", () => {
    const now = makeDateAt("2026-05-20T11:00", "Asia/Seoul");
    expect(classifySession(TICKER, "2026-05-20", now)).toBe("intraday");
  });

  it("Thu 15:29 KST (1 minute before 15:30), asOf=today → intraday", () => {
    const now = makeDateAt("2026-05-21T15:29", "Asia/Seoul");
    expect(classifySession(TICKER, "2026-05-21", now)).toBe("intraday");
  });

  it("Thu 15:30 KST exactly, asOf=today → intraday (still in 30min buffer)", () => {
    const now = makeDateAt("2026-05-21T15:30", "Asia/Seoul");
    expect(classifySession(TICKER, "2026-05-21", now)).toBe("intraday");
  });

  it("Thu 16:00 KST (30min after 15:30), asOf=today → closed", () => {
    const now = makeDateAt("2026-05-21T16:00", "Asia/Seoul");
    expect(classifySession(TICKER, "2026-05-21", now)).toBe("closed");
  });

  it("Thu 23:59 KST, asOf=today → closed", () => {
    const now = makeDateAt("2026-05-21T23:59", "Asia/Seoul");
    expect(classifySession(TICKER, "2026-05-21", now)).toBe("closed");
  });

  it("Thu 11:00 KST, asOf=yesterday → stale", () => {
    const now = makeDateAt("2026-05-21T11:00", "Asia/Seoul");
    expect(classifySession(TICKER, "2026-05-20", now)).toBe("stale");
  });

  it("Saturday 11:00 KST, asOf=today (the Saturday) → stale (no trading)", () => {
    const now = makeDateAt("2026-05-23T11:00", "Asia/Seoul"); // Sat
    expect(classifySession(TICKER, "2026-05-23", now)).toBe("stale");
  });
});

describe("market-session.classifySession — US ticker", () => {
  const TICKER = "AAPL";

  it("ET 11:00 weekday, asOf=today → intraday", () => {
    const now = makeDateAt("2026-05-21T11:00", "America/New_York");
    expect(classifySession(TICKER, "2026-05-21", now)).toBe("intraday");
  });

  it("ET 16:00 exactly, asOf=today → intraday (still in 30min buffer)", () => {
    const now = makeDateAt("2026-05-21T16:00", "America/New_York");
    expect(classifySession(TICKER, "2026-05-21", now)).toBe("intraday");
  });

  it("ET 16:30 close+buffer, asOf=today → closed", () => {
    const now = makeDateAt("2026-05-21T16:30", "America/New_York");
    expect(classifySession(TICKER, "2026-05-21", now)).toBe("closed");
  });

  it("ET 11:00, asOf=yesterday → stale", () => {
    const now = makeDateAt("2026-05-21T11:00", "America/New_York");
    expect(classifySession(TICKER, "2026-05-20", now)).toBe("stale");
  });
});

describe("market-session.priceLabelFor — Korean labels for LastClose card", () => {
  it("intraday → '장중 가격 (마감 후 확정)' (NEVER '최종 종가')", () => {
    const now = makeDateAt("2026-05-21T11:00", "Asia/Seoul");
    const label = priceLabelFor("068930.KQ", "2026-05-21", now);
    expect(label).toBe("장중 가격 (마감 후 확정)");
    expect(label).not.toMatch(/^최종 종가$/);
  });

  it("closed → '최종 종가'", () => {
    const now = makeDateAt("2026-05-21T18:00", "Asia/Seoul");
    expect(priceLabelFor("068930.KQ", "2026-05-21", now)).toBe("최종 종가");
  });

  it("stale → '최종 종가 — 직전 거래일'", () => {
    const now = makeDateAt("2026-05-21T11:00", "Asia/Seoul");
    expect(priceLabelFor("068930.KQ", "2026-05-20", now))
      .toBe("최종 종가 — 직전 거래일");
  });
});

describe("market-session — locked invariant: intraday NEVER labelled 최종 종가", () => {
  // Sample 24 hours × KR + US, asOf=today. If `now` is within trading
  // session (any time before cutoff on a weekday), the label MUST NOT
  // be the bare "최종 종가". This is the exact phrasing the user keeps
  // seeing show up incorrectly.
  it("KR — every weekday 09:00..15:29 with asOf=today never says '최종 종가'", () => {
    const today = "2026-05-21"; // Thursday
    for (let m = 9 * 60; m < 15 * 60 + 30; m += 15) {
      const h = Math.floor(m / 60);
      const mm = m % 60;
      const ts = `${today}T${String(h).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
      const now = makeDateAt(ts, "Asia/Seoul");
      const label = priceLabelFor("068930.KQ", today, now);
      expect(label, `at ${ts} KST, label was "${label}"`)
        .not.toBe("최종 종가");
    }
  });
});
