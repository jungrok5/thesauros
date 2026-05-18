/**
 * Auth gate at the edge — preserves the user's original URL so a
 * shared stock-detail link (`/stocks/017670.KS`) actually opens that
 * page after sign-in, instead of dropping the recipient on /dashboard.
 *
 * Strategy: any request to a protected route that arrives without a
 * NextAuth session cookie is redirected to `/login?callbackUrl=<original>`.
 * The login page reads `callbackUrl` and passes it to `signIn()` so
 * Google's redirect lands on the original page.
 *
 * NB: this is a cookie presence check, not a session validity check.
 * The (app)/layout.tsx still runs `await auth()` to enforce real
 * session + access_status — middleware just captures the URL so the
 * post-login redirect has somewhere meaningful to go.
 */
import { NextRequest, NextResponse } from "next/server";

const SESSION_COOKIES = [
  "authjs.session-token",
  "__Secure-authjs.session-token",
];

export function middleware(req: NextRequest) {
  const { pathname, search } = req.nextUrl;

  // Public routes — don't gate. Static assets and the login/pending
  // pages themselves must always be reachable.
  const PUBLIC_PREFIXES = ["/login", "/pending", "/api/auth", "/_next", "/favicon"];
  if (PUBLIC_PREFIXES.some((p) => pathname.startsWith(p))) {
    return NextResponse.next();
  }

  const hasSession = SESSION_COOKIES.some(
    (n) => req.cookies.get(n)?.value,
  );
  if (hasSession) return NextResponse.next();

  // Build login URL with the original path preserved so signIn() can
  // round-trip the user back to where they were trying to go.
  const callback = pathname + (search || "");
  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.search = `?callbackUrl=${encodeURIComponent(callback)}`;
  return NextResponse.redirect(url);
}

export const config = {
  // Skip middleware on static asset paths to avoid per-request overhead.
  // Next.js's own _next/* and image optimizer paths are excluded by the
  // negative lookahead.
  matcher: ["/((?!_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml).*)"],
};
