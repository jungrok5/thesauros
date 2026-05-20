/**
 * /api/watchlist-groups — 사용자 정의 관심 그룹 CRUD.
 *
 *  GET    /api/watchlist-groups          → 사용자 그룹 목록 (order_index ASC)
 *  POST   /api/watchlist-groups          → { name, color? }            create
 *  PATCH  /api/watchlist-groups          → { id, name?, color?, order_index? }  update
 *  DELETE /api/watchlist-groups?id=N     → 그룹 삭제 (watchlist.group_id → NULL)
 */
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { ensureUserId, getServerClient } from "@/lib/supabase";

export const dynamic = "force-dynamic";

const NAME_MAX = 50;
// Tailwind 색 token. UI 가 안전한 6 개만 노출 — 임의 hex 입력 금지.
const ALLOWED_COLORS = new Set([
  "emerald", "sky", "amber", "violet", "rose", "zinc",
]);

async function currentUser() {
  const session = await auth();
  if (!session?.user?.email) return null;
  return {
    email: session.user.email.toLowerCase(),
    name: session.user.name ?? null,
  };
}

function dbError(err: { message?: string } | null): NextResponse {
  if (err) console.error("watchlist-groups:", err.message);
  return NextResponse.json({ error: "db error" }, { status: 500 });
}

export async function GET() {
  const user = await currentUser();
  if (!user) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const userId = await ensureUserId(user.email, user.name);
  const sb = getServerClient();
  const { data, error } = await sb
    .from("watchlist_groups")
    .select("id, name, color, order_index, created_at")
    .eq("user_id", userId)
    .order("order_index", { ascending: true })
    .order("created_at", { ascending: true });
  if (error) return dbError(error);
  return NextResponse.json({ groups: data });
}

export async function POST(req: NextRequest) {
  const user = await currentUser();
  if (!user) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const body = await req.json().catch(() => ({}));
  const name = String(body.name ?? "").trim().slice(0, NAME_MAX);
  if (!name) return NextResponse.json({ error: "name required" }, { status: 400 });
  const color = ALLOWED_COLORS.has(String(body.color))
    ? String(body.color) : null;

  const userId = await ensureUserId(user.email, user.name);
  const sb = getServerClient();
  // order_index: 마지막 + 1 — 새 그룹은 항상 끝에 붙음
  const { data: maxRow } = await sb
    .from("watchlist_groups")
    .select("order_index")
    .eq("user_id", userId)
    .order("order_index", { ascending: false })
    .limit(1)
    .maybeSingle();
  const nextIdx = (maxRow?.order_index ?? -1) + 1;

  const { data, error } = await sb
    .from("watchlist_groups")
    .insert({ user_id: userId, name, color, order_index: nextIdx })
    .select()
    .single();
  if (error) {
    // Unique violation = 같은 이름 그룹 이미 있음
    if (error.message?.includes("watchlist_groups_user_id_name_key")) {
      return NextResponse.json(
        { error: "duplicate name" }, { status: 409 });
    }
    return dbError(error);
  }
  return NextResponse.json({ group: data });
}

export async function PATCH(req: NextRequest) {
  const user = await currentUser();
  if (!user) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const body = await req.json().catch(() => ({}));
  const id = Number(body.id);
  if (!Number.isInteger(id) || id <= 0) {
    return NextResponse.json({ error: "id required" }, { status: 400 });
  }
  const update: Record<string, unknown> = {};
  if (typeof body.name === "string") {
    const name = body.name.trim().slice(0, NAME_MAX);
    if (!name) return NextResponse.json({ error: "name empty" }, { status: 400 });
    update.name = name;
  }
  if ("color" in body) {
    update.color = ALLOWED_COLORS.has(String(body.color)) ? String(body.color) : null;
  }
  if ("order_index" in body && Number.isInteger(Number(body.order_index))) {
    update.order_index = Number(body.order_index);
  }
  if (Object.keys(update).length === 0) {
    return NextResponse.json({ error: "no fields" }, { status: 400 });
  }

  const userId = await ensureUserId(user.email, user.name);
  const sb = getServerClient();
  // user_id 매치 강제 — 남의 그룹 수정 금지
  const { data, error } = await sb
    .from("watchlist_groups")
    .update(update)
    .eq("id", id)
    .eq("user_id", userId)
    .select()
    .single();
  if (error) {
    if (error.message?.includes("watchlist_groups_user_id_name_key")) {
      return NextResponse.json(
        { error: "duplicate name" }, { status: 409 });
    }
    return dbError(error);
  }
  return NextResponse.json({ group: data });
}

export async function DELETE(req: NextRequest) {
  const user = await currentUser();
  if (!user) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const id = Number(new URL(req.url).searchParams.get("id"));
  if (!Number.isInteger(id) || id <= 0) {
    return NextResponse.json({ error: "id required" }, { status: 400 });
  }
  const userId = await ensureUserId(user.email, user.name);
  const sb = getServerClient();
  // watchlist.group_id 는 FK ON DELETE SET NULL — 종목은 미분류로 자동 이동.
  const { error } = await sb
    .from("watchlist_groups")
    .delete()
    .eq("id", id)
    .eq("user_id", userId);
  if (error) return dbError(error);
  return NextResponse.json({ ok: true });
}
