/**
 * Pins the 2026-05-27 separation: paper-buy must NOT auto-upsert a
 * watchlist row.
 *
 * Earlier, `POST /api/paper` upserted a watchlist row with
 * `category='holding'` "so pattern alerts start firing", which made
 * every 모의 매수 (simulation) silently appear in the 보유 list on the
 * watchlist page. User-visible bleed of simulation into the holdings
 * UI.
 *
 * Decoupled: paper has its own alerts (notify_paper_alerts —
 * initial_stop_loss / target). If a user wants the system pattern
 * alerts on a paper-bought ticker, they explicitly add it to
 * watchlist from the stock detail page.
 *
 * This is a source-level static check (the route can't be unit-
 * tested without a real Supabase mock). It greps the route file
 * for the specific upsert pattern. If anyone re-introduces the
 * coupling, this test fails.
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

describe("POST /api/paper — must not touch watchlist", () => {
  const src = readFileSync(
    resolve(__dirname, "../app/api/paper/route.ts"),
    "utf-8",
  );

  it("does not upsert or insert into watchlist", () => {
    // The smoking-gun pattern was: sb.from("watchlist").upsert({...})
    expect(src).not.toMatch(/from\(["']watchlist["']\)\s*\.\s*upsert/);
    expect(src).not.toMatch(/from\(["']watchlist["']\)\s*\.\s*insert/);
  });

  it("does not mention category: 'holding' as a side effect", () => {
    // Any code that hard-codes holding in this file is a red flag —
    // paper-buy must not set or update a holding row.
    expect(src).not.toMatch(/category:\s*["']holding["']/);
  });
});
