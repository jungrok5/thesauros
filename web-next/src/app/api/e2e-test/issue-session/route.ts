/**
 * Test-only endpoint to mint a NextAuth session cookie for Playwright.
 *
 * Guards (defense in depth):
 *   1. NODE_ENV === 'production' AND ALLOW_E2E_IN_PROD !== '1' → 404.
 *   2. E2E_TEST_TOKEN must be set AND ≥16 chars → 404 otherwise.
 *   3. `x-e2e-token` header must match via constant-time compare → 403.
 *   4. Email must be in AUTH_ALLOWED_EMAILS → 400.
 *
 * Returns: { cookieName, value, expiresAt }
 */
import { NextRequest, NextResponse } from "next/server";
import { encode } from "next-auth/jwt";
import { timingSafeEqual } from "crypto";

export const dynamic = "force-dynamic";

const IS_PROD = process.env.NODE_ENV === "production";
const PROD_ALLOWED = process.env.ALLOW_E2E_IN_PROD === "1";

function expectedToken(): string | null {
  return process.env.E2E_TEST_TOKEN ?? null;
}

function allowedEmail(email: string): boolean {
  const allowed = (process.env.AUTH_ALLOWED_EMAILS ?? "")
    .split(",")
    .map((e) => e.trim().toLowerCase())
    .filter(Boolean);
  return allowed.includes(email.toLowerCase());
}

function constantTimeMatches(got: string, expected: string): boolean {
  const a = Buffer.from(got, "utf8");
  const b = Buffer.from(expected, "utf8");
  if (a.length !== b.length) return false;
  return timingSafeEqual(a, b);
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
  if (!email || !allowedEmail(email)) {
    return NextResponse.json({ error: "email not in allowlist" }, { status: 400 });
  }

  const secret = process.env.AUTH_SECRET;
  if (!secret) {
    return NextResponse.json({ error: "AUTH_SECRET missing" }, { status: 500 });
  }

  const expiresIn = 60 * 60;
  const now = Math.floor(Date.now() / 1000);
  const token = await encode({
    token: {
      sub: `test-user-${email}`,
      email,
      name: email.split("@")[0],
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
  });
}
