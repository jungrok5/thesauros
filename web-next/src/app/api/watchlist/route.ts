/**
 * GET    /api/watchlist            — list current user's watchlist
 * POST   /api/watchlist            — add { ticker, category?, note? }
 * DELETE /api/watchlist?ticker=... — remove by ticker
 */
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { ensureUserId, getServerClient } from "@/lib/supabase";
import { ensureTickerInMaster } from "@/lib/ensure-ticker";
// dispatchAnalyzeTicker import removed 2026-05-28.
// See the "Fire-and-forget" comment below for the why.

export const dynamic = "force-dynamic";

const TICKER_RE = /^[A-Z0-9]{1,12}(\.[A-Z]{1,4})?$/i;
const DATE_RE   = /^\d{4}-\d{2}-\d{2}$/;
const NOTE_MAX  = 500;
const IS_PROD = process.env.NODE_ENV === "production";

/** Map a DB error to a safe response. Real error logged server-side only. */
function dbError(err: { message?: string } | null, fallback = "db error"): NextResponse {
  if (err) console.error("supabase error:", err.message);
  return NextResponse.json(
    { error: fallback, ...(IS_PROD ? {} : { detail: err?.message }) },
    { status: 500 },
  );
}

async function currentUser() {
  const session = await auth();
  if (!session?.user?.email) return null;
  return {
    email: session.user.email.toLowerCase(),
    name: session.user.name ?? null,
  };
}

export async function GET() {
  const user = await currentUser();
  if (!user) return NextResponse.json({ error: "unauthorized" }, { status: 401 });

  const userId = await ensureUserId(user.email, user.name);
  const sb = getServerClient();
  const { data, error } = await sb
    .from("watchlist")
    .select("id, ticker, category, group_id, entry_price, entry_date, note, alerts_enabled, created_at")
    .eq("user_id", userId)
    .order("created_at", { ascending: false });
  if (error) return dbError(error);
  return NextResponse.json({ items: data });
}

export async function POST(req: NextRequest) {
  const user = await currentUser();
  if (!user) return NextResponse.json({ error: "unauthorized" }, { status: 401 });

  const body = await req.json().catch(() => ({}));
  const ticker = String(body.ticker ?? "").trim().toUpperCase();
  if (!TICKER_RE.test(ticker)) {
    return NextResponse.json({ error: "invalid ticker" }, { status: 400 });
  }
  const category = (body.category === "holding" ? "holding" : "observing") as
    | "observing"
    | "holding";
  const note = body.note ? String(body.note).slice(0, NOTE_MAX) : null;
  const ep = Number(body.entry_price);
  const entryPrice = Number.isFinite(ep) && ep > 0 ? ep : null;
  const entryDate = body.entry_date && DATE_RE.test(String(body.entry_date))
    ? String(body.entry_date)
    : null;
  const targetPrice = Number.isFinite(Number(body.target_price)) && Number(body.target_price) > 0
    ? Number(body.target_price) : null;
  const targetPct = Number.isFinite(Number(body.target_pct_from_entry))
    ? Number(body.target_pct_from_entry) : null;
  const stopPrice = Number.isFinite(Number(body.stop_price)) && Number(body.stop_price) > 0
    ? Number(body.stop_price) : null;
  const stopPct = Number.isFinite(Number(body.stop_pct_from_entry))
    ? Number(body.stop_pct_from_entry) : null;
  // group_id: null = 미분류 (관심 종목 페이지 기본 그룹). number = 사용자 정의 그룹.
  // 클라이언트가 group_id 를 안 넘기면 (undefined) UPSERT 시 NULL 처리.
  // typeof guard 추가 (2026-05-20) — `[]` / `{}` 같은 비정상 입력이
  // Number([]) === 0 으로 coerce 되어 group_id=0 (FK violation) 으로
  // 새는 것 차단.
  const rawGroup = body.group_id;
  const groupId =
    rawGroup == null || rawGroup === ""
      ? null
      : (typeof rawGroup === "number" || typeof rawGroup === "string") &&
          Number.isInteger(Number(rawGroup)) &&
          Number(rawGroup) > 0
        ? Number(rawGroup)
        : null;

  // FK guard: `watchlist.ticker` references `tickers.ticker`. If a user
  // hits this with a ticker that isn't yet in our master (US name
  // resolved via Naver, brand-name fuzzy match, etc.), the FK would
  // 500 the request. Seed the row on demand — but ONLY if Naver
  // recognizes the ticker. A bare "FAKETICKERZZZ" string is refused
  // here, returning 400 instead of polluting the master.
  const ensured = await ensureTickerInMaster(ticker);
  if (!ensured.ok) {
    return NextResponse.json(
      { error: "unknown ticker", ticker },
      { status: 400 },
    );
  }

  const userId = await ensureUserId(user.email, user.name);
  const sb = getServerClient();

  // Re-arm 🎯 target / 🛑 stop alerts when the user actually changed the
  // threshold. Without this, telegram_worker's one-shot `*_hit_at`
  // marker would silently suppress alerts at the new level.
  const { data: existing } = await sb
    .from("watchlist")
    .select("target_price, target_pct_from_entry, stop_price, stop_pct_from_entry, entry_price, entry_date")
    .eq("user_id", userId)
    .eq("ticker", ticker)
    .maybeSingle();
  const wasNewAdd = existing == null;

  // 2026-05-28 — entry_price auto-snapshot. When a user adds a ticker
  // to the watchlist, snapshot the latest weekly close as the "I
  // started tracking here" reference price. The watchlist UI then
  // shows entry_price / current_price / return % so every tracked
  // ticker is automatically a "what if I had bought when I added it"
  // experiment. Only snapshots when:
  //   - first time adding this ticker (wasNewAdd), AND
  //   - body didn't explicitly provide entry_price (preserves user override).
  let snappedEntryPrice = entryPrice;
  let snappedEntryDate = entryDate;
  if (wasNewAdd && entryPrice == null) {
    const { data: latestBar } = await sb
      .from("bars")
      .select("close, bar_date")
      .eq("ticker", ticker)
      .eq("granularity", "W")
      .order("bar_date", { ascending: false })
      .limit(1)
      .maybeSingle();
    if (latestBar?.close != null) {
      snappedEntryPrice = Number(latestBar.close);
      snappedEntryDate = String(latestBar.bar_date);
    }
  }
  // For an existing row whose user did not pass entry_price, keep the
  // already-recorded entry_price (don't reset on category swap etc).
  if (!wasNewAdd && entryPrice == null && existing?.entry_price != null) {
    snappedEntryPrice = Number(existing.entry_price);
    snappedEntryDate = existing.entry_date ? String(existing.entry_date) : null;
  }

  // 2026-05-28 — target / stop auto-fill on first add. Priority:
  //   1. body provided → keep (user override always wins)
  //   2. analyze_results.entry_plan (book-grounded analyzer output)
  //   3. fallback default: target = entry × 1.20, stop = entry × 0.90
  // Existing rows preserve their values; only wasNewAdd triggers fill.
  let autoTargetPrice = targetPrice;
  let autoStopPrice = stopPrice;
  if (wasNewAdd && snappedEntryPrice != null && snappedEntryPrice > 0) {
    if (autoTargetPrice == null || autoStopPrice == null) {
      const { data: ar } = await sb
        .from("analyze_results")
        .select("result")
        .eq("ticker", ticker)
        .maybeSingle();
      const plan = (ar?.result as { entry_plan?: { entry?: number | string;
        stop?: number | string; target?: number | string } } | null)
        ?.entry_plan ?? null;
      if (autoTargetPrice == null) {
        const planTarget = plan?.target != null ? Number(plan.target) : null;
        autoTargetPrice = Number.isFinite(planTarget) && (planTarget as number) > 0
          ? (planTarget as number)
          : Math.round(snappedEntryPrice * 1.20);
      }
      if (autoStopPrice == null) {
        const planStop = plan?.stop != null ? Number(plan.stop) : null;
        autoStopPrice = Number.isFinite(planStop) && (planStop as number) > 0
          ? (planStop as number)
          : Math.round(snappedEntryPrice * 0.90);
      }
    }
  }
  // Preserve existing target/stop on category swap (same as entry_price).
  if (!wasNewAdd && targetPrice == null && existing?.target_price != null) {
    autoTargetPrice = Number(existing.target_price);
  }
  if (!wasNewAdd && stopPrice == null && existing?.stop_price != null) {
    autoStopPrice = Number(existing.stop_price);
  }
  const resetTarget =
    existing != null &&
    (Number(existing.target_price) !== Number(targetPrice) ||
      Number(existing.target_pct_from_entry) !== Number(targetPct));
  const resetStop =
    existing != null &&
    (Number(existing.stop_price) !== Number(stopPrice) ||
      Number(existing.stop_pct_from_entry) !== Number(stopPct));

  const payload: Record<string, unknown> = {
    user_id: userId, ticker, category, note,
    group_id: groupId,
    entry_price: snappedEntryPrice, entry_date: snappedEntryDate,
    target_price: autoTargetPrice,
    target_pct_from_entry: targetPct,
    stop_price: autoStopPrice,
    stop_pct_from_entry: stopPct,
  };
  if (resetTarget) payload.target_hit_at = null;
  if (resetStop) payload.stop_hit_at = null;

  const { data, error } = await sb
    .from("watchlist")
    .upsert(payload, { onConflict: "user_id,ticker" })
    .select()
    .single();
  if (error) return dbError(error);

  // 2026-05-28 — Analyze Single Ticker dispatch removed.
  //
  // Was: on wasNewAdd we'd workflow_dispatch analyze-ticker.yml so the
  //   new ticker got "instant analysis" (~2-3 min) instead of waiting
  //   for Friday 17:30 weekly-scan.
  // Problems this created (user feedback 2026-05-28):
  //   1. analyze_results for that one ticker stamped with mid-week
  //      time, breaking the site-wide "분석 시각: 5/24" consistency.
  //   2. Mid-week incomplete weekly bar produced different results
  //      than Friday weekly-close would — same ticker flipped from
  //      #1 to outside top-10 after a Thursday re-analysis.
  //   3. The workflow's last step ran telegram_worker which scanned
  //      ALL active signals, causing concurrent-dispatch race
  //      duplicates (mitigated by pg_try_advisory_lock in cd2fe5c
  //      but still wasted work).
  // The book strategy is weekly-close based; users acting on mid-week
  // snapshots is the anti-pattern the book warns against. Removing
  // the dispatch makes everything consistent: site-wide analysis
  // refresh happens once on Friday 17:30 KST, period. Newly-added
  // tickers display the existing Friday snapshot (already analyzed
  // as part of the full ~2700-ticker universe).
  //
  // analyze-ticker.yml workflow file kept — still useful for
  // operator-initiated manual re-analysis.

  return NextResponse.json({ item: data });
}

/**
 * PATCH /api/watchlist  — { id, group_id?, category? }
 *
 * Lightweight update for a single field — currently group_id (그룹 이동) +
 * category (관심 ↔ 보유 전환). Doesn't touch entry/target/stop fields
 * (use POST for those, which goes through the full upsert path).
 */
export async function PATCH(req: NextRequest) {
  const user = await currentUser();
  if (!user) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const body = await req.json().catch(() => ({}));
  const id = Number(body.id);
  if (!Number.isInteger(id) || id <= 0) {
    return NextResponse.json({ error: "id required" }, { status: 400 });
  }

  const update: Record<string, unknown> = {};
  if ("group_id" in body) {
    const g = body.group_id;
    update.group_id =
      g == null || g === ""
        ? null
        : (typeof g === "number" || typeof g === "string") &&
            Number.isInteger(Number(g)) &&
            Number(g) > 0
          ? Number(g)
          : null;
  }
  if (body.category === "holding" || body.category === "observing") {
    update.category = body.category;
  }
  if (Object.keys(update).length === 0) {
    return NextResponse.json({ error: "no fields" }, { status: 400 });
  }

  const userId = await ensureUserId(user.email, user.name);
  const sb = getServerClient();
  const { data, error } = await sb
    .from("watchlist")
    .update(update)
    .eq("id", id)
    .eq("user_id", userId)
    .select()
    .single();
  if (error) return dbError(error);
  return NextResponse.json({ item: data });
}

export async function DELETE(req: NextRequest) {
  const user = await currentUser();
  if (!user) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const url = new URL(req.url);
  const ticker = (url.searchParams.get("ticker") ?? "").toUpperCase();
  if (!TICKER_RE.test(ticker)) {
    return NextResponse.json({ error: "invalid ticker" }, { status: 400 });
  }

  const userId = await ensureUserId(user.email, user.name);
  const sb = getServerClient();
  const { error } = await sb
    .from("watchlist")
    .delete()
    .eq("user_id", userId)
    .eq("ticker", ticker);
  if (error) return dbError(error);
  return NextResponse.json({ ok: true });
}
