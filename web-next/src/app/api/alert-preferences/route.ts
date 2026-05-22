/**
 * GET /api/alert-preferences  → current settings (or defaults)
 * PUT /api/alert-preferences  → upsert with merged updates
 */
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { ensureUserId, getServerClient } from "@/lib/supabase";

export const dynamic = "force-dynamic";

const FIELDS = [
  "enable_enter",
  "enable_pyramid",
  "enable_warn",
  "enable_exit",
  "enable_ma240_break",
  "enable_quarter_25_break",
  "enable_daily_top5",
  "enable_disclosure",
  // 와병투자 모드 — 책의 이상적 사용자 모습 ("한달 누워있다 1회만 확인").
  // ON 이면 telegram_worker 가 위 모든 enable_* 토글을 무시하고 주 1회
  // 통합 요약만 발사. (migration 044)
  "bedrest_mode",
] as const;

const DEFAULTS: Record<(typeof FIELDS)[number], boolean> = {
  enable_enter: true,
  enable_pyramid: true,
  enable_warn: true,
  enable_exit: true,
  enable_ma240_break: true,
  enable_quarter_25_break: true,
  enable_daily_top5: false,
  enable_disclosure: true,
  bedrest_mode: false,
};

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
  const { data } = await sb
    .from("alert_preferences")
    .select("*")
    .eq("user_id", userId)
    .maybeSingle();
  return NextResponse.json({ prefs: { ...DEFAULTS, ...(data ?? {}) } });
}

export async function PUT(req: NextRequest) {
  const user = await currentUser();
  if (!user) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const body = await req.json().catch(() => ({}));
  const update: Record<string, boolean> = {};
  for (const f of FIELDS) {
    if (typeof body[f] === "boolean") update[f] = body[f];
  }
  if (!Object.keys(update).length) {
    return NextResponse.json({ error: "no valid fields" }, { status: 400 });
  }
  const userId = await ensureUserId(user.email, user.name);
  const sb = getServerClient();
  const { data, error } = await sb
    .from("alert_preferences")
    .upsert({ user_id: userId, ...update }, { onConflict: "user_id" })
    .select()
    .single();
  if (error) {
    console.error("alert prefs:", error.message);
    return NextResponse.json({ error: "db error" }, { status: 500 });
  }
  return NextResponse.json({ prefs: { ...DEFAULTS, ...data } });
}
