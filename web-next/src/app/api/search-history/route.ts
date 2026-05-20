/**
 * /api/search-history — log the user's search submissions.
 *
 *   POST  body: { query: string; ticker?: string }
 *      Insert a row; the AFTER INSERT trigger trims to 30 newest per user.
 *      Fire-and-forget from the client — caller doesn't block on success.
 *
 *   DELETE  clear the user's entire history (privacy / "clear recent").
 *
 * The /stocks page reads history server-side via the supabase client +
 * the user's session, so no GET endpoint is needed here.
 */
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { ensureUserId, getServerClient } from "@/lib/supabase";

export const dynamic = "force-dynamic";

const QUERY_MAX = 80;
const TICKER_MAX = 20;

async function currentUserId(): Promise<string | null> {
  const session = await auth();
  if (!session?.user?.email) return null;
  return await ensureUserId(
    session.user.email.toLowerCase(),
    session.user.name ?? null,
  );
}

export async function POST(req: NextRequest) {
  const userId = await currentUserId();
  if (!userId) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const body = await req.json().catch(() => ({}));
  const query = String(body.query ?? "").trim();
  const ticker = body.ticker
    ? String(body.ticker).trim().toUpperCase().slice(0, TICKER_MAX)
    : null;
  if (!query || query.length > QUERY_MAX) {
    return NextResponse.json({ error: "invalid query" }, { status: 400 });
  }

  // UPSERT — 같은 (user_id, query) 가 이미 있으면 created_at 만
  // 갱신해서 가장 최근 위치로 끌어올림. UNIQUE INDEX 가 migration
  // 028 에서 잡혀 있어 onConflict 가 그대로 동작.
  // ticker 도 갱신 — 처음에 미해소 (null) 였다가 나중에 canonical
  // ticker 가 풀린 경우 정확한 값으로 덮어씀.
  const sb = getServerClient();
  const { error } = await sb
    .from("search_history")
    .upsert(
      {
        user_id: userId,
        query,
        ticker,
        created_at: new Date().toISOString(),
      },
      { onConflict: "user_id,query" },
    );
  if (error) {
    console.error("search_history upsert:", error.message);
    return NextResponse.json({ error: "db error" }, { status: 500 });
  }
  return NextResponse.json({ ok: true });
}

export async function DELETE() {
  const userId = await currentUserId();
  if (!userId) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const sb = getServerClient();
  const { error } = await sb
    .from("search_history")
    .delete()
    .eq("user_id", userId);
  if (error) {
    console.error("search_history delete:", error.message);
    return NextResponse.json({ error: "db error" }, { status: 500 });
  }
  return NextResponse.json({ ok: true });
}
