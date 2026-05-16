/**
 * Test-only endpoint to mint a NextAuth session cookie for Playwright.
 *
 * Guards:
 *  - Returns 404 unless NODE_ENV === 'development' OR E2E_TEST_TOKEN is set.
 *  - Requires `x-e2e-token` header to match `E2E_TEST_TOKEN`.
 *  - Only signs sessions for emails in AUTH_ALLOWED_EMAILS (same allowlist
 *    as production sign-in).
 *
 * Returns: { cookieName, value, expiresAt }
 */
import { NextRequest, NextResponse } from "next/server";
import { encode } from "next-auth/jwt";

export const dynamic = "force-dynamic";

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

export async function POST(req: NextRequest) {
  const expected = expectedToken();
  if (!expected) {
    // Endpoint disabled — no E2E token configured.
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  if (req.headers.get("x-e2e-token") !== expected) {
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

  const expiresIn = 60 * 60; // 1 hour
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
