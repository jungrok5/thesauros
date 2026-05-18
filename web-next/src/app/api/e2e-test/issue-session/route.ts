/**
 * Test-only endpoint to mint a NextAuth session cookie for Playwright.
 *
 * Guards (defense in depth):
 *   1. NODE_ENV === 'production' AND ALLOW_E2E_IN_PROD !== '1' → 404.
 *   2. E2E_TEST_TOKEN must be set AND ≥16 chars → 404 otherwise.
 *   3. `x-e2e-token` header must match via constant-time compare → 403.
 *
 * Body: { email: string, role?: 'admin'|'user', access_status?: 'pending'|'approved'|'rejected' }
 * Returns: { cookieName, value, expiresAt, userId }
 *
 * Upserts the user into `users` so the proxy's role/access_status checks
 * have something to read.
 */
import { NextRequest, NextResponse } from "next/server";
import { encode } from "next-auth/jwt";
import { timingSafeEqual } from "crypto";
import { getServerClient } from "@/lib/supabase";

export const dynamic = "force-dynamic";

const IS_PROD = process.env.NODE_ENV === "production";
const PROD_ALLOWED = process.env.ALLOW_E2E_IN_PROD === "1";

const EMAIL_RE = /^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$/i;

function expectedToken(): string | null {
  return process.env.E2E_TEST_TOKEN ?? null;
}

function constantTimeMatches(got: string, expected: string): boolean {
  const a = Buffer.from(got, "utf8");
  const b = Buffer.from(expected, "utf8");
  if (a.length !== b.length) return false;
  return timingSafeEqual(a, b);
}

/**
 * Rolling GC — drop @e2e.test users older than ~1 hour each time we
 * mint a session. Keeps the prod users table from accumulating test
 * artifacts even when retention.py hasn't run today. Best-effort:
 * if it errors we still issue the session.
 */
async function purgeStaleTestUsers(sb: ReturnType<typeof getServerClient>) {
  try {
    const oneHourAgo = new Date(Date.now() - 60 * 60 * 1000).toISOString();
    await sb
      .from("users")
      .delete()
      .ilike("email", "%@e2e.test")
      .lt("created_at", oneHourAgo);
  } catch (e) {
    console.error("e2e GC:", e);
  }
}

async function upsertTestUser(
  email: string,
  role: "admin" | "user",
  status: "pending" | "approved" | "rejected",
): Promise<string> {
  const sb = getServerClient();
  await purgeStaleTestUsers(sb);
  const { data: existing } = await sb
    .from("users")
    .select("id")
    .eq("email", email)
    .maybeSingle();
  if (existing) {
    await sb
      .from("users")
      .update({
        role,
        access_status: status,
        approved_at: status === "approved" ? new Date().toISOString() : null,
        last_login_at: new Date().toISOString(),
      })
      .eq("id", existing.id);
    return existing.id as string;
  }
  const { data: inserted, error } = await sb
    .from("users")
    .insert({
      email,
      name: email.split("@")[0],
      role,
      access_status: status,
      approved_at: status === "approved" ? new Date().toISOString() : null,
      last_login_at: new Date().toISOString(),
    })
    .select("id")
    .single();
  if (error) throw error;
  return inserted.id as string;
}

export async function POST(req: NextRequest) {
  if (IS_PROD && !PROD_ALLOWED) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  const expected = expectedToken();
  if (!expected || expected.length < 16) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  const got = req.headers.get("x-e2e-token") ?? "";
  if (!constantTimeMatches(got, expected)) {
    return NextResponse.json({ error: "forbidden" }, { status: 403 });
  }
  const body = await req.json().catch(() => ({}));
  const email = String(body.email ?? "").toLowerCase();
  if (!email || !EMAIL_RE.test(email)) {
    return NextResponse.json({ error: "invalid email" }, { status: 400 });
  }
  const role: "admin" | "user" = body.role === "admin" ? "admin" : "user";
  const access_status: "pending" | "approved" | "rejected" =
    body.access_status === "pending" || body.access_status === "rejected"
      ? body.access_status
      : "approved";

  const secret = process.env.AUTH_SECRET;
  if (!secret) {
    return NextResponse.json({ error: "AUTH_SECRET missing" }, { status: 500 });
  }

  let userId: string;
  try {
    userId = await upsertTestUser(email, role, access_status);
  } catch (e) {
    console.error("e2e upsertTestUser:", e);
    return NextResponse.json({ error: "db error" }, { status: 500 });
  }

  const expiresIn = 60 * 60;
  const now = Math.floor(Date.now() / 1000);
  const token = await encode({
    token: {
      sub: userId,
      email,
      name: email.split("@")[0],
      role,
      access_status,
      iat: now,
      exp: now + expiresIn,
      jti: `e2e-${now}`,
    },
    secret,
    salt: "authjs.session-token",
    maxAge: expiresIn,
  });

  return NextResponse.json({
    cookieName: "authjs.session-token",
    value: token,
    expiresAt: now + expiresIn,
    userId,
  });
}
