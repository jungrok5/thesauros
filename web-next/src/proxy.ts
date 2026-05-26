import { auth } from "@/auth";
import { NextResponse } from "next/server";

const PENDING_PATH = "/pending";
const ADMIN_PATH = "/admin";

export default auth((req) => {
  const isLoggedIn = !!req.auth;
  const { nextUrl } = req;
  const pathname = nextUrl.pathname;

  const isPublic =
    pathname === "/login" ||
    pathname.startsWith("/api/auth") ||
    // Test-only session minter — guarded inside the handler by E2E_TEST_TOKEN.
    pathname.startsWith("/api/e2e-test/") ||
    // Telegram webhook — guarded inside the handler by TELEGRAM_WEBHOOK_SECRET.
    pathname === "/api/telegram/webhook" ||
    // Vercel Cron → workflow_dispatch — guarded inside the handler by
    // verifyCronAuth() comparing Authorization: Bearer ${CRON_SECRET}.
    // Without this, NextAuth middleware below 401s every cron tick
    // before _dispatch.ts can run, silently breaking daily-data /
    // weekly-scan dispatch (root cause of macro_state staleness
    // 2026-05-22 onward).
    pathname.startsWith("/api/cron/") ||
    pathname.startsWith("/_next") ||
    pathname === "/favicon.ico" ||
    pathname === "/manifest.webmanifest" ||
    pathname === "/sw.js" ||
    // Social-preview crawlers (KakaoTalk, Facebook, Slack, Twitter, …)
    // fetch these without a session — keeping them behind auth made link
    // previews show a blank /login redirect instead of the OG image.
    // Next.js exposes opengraph-image.tsx / icon.tsx at these literal
    // paths; the trailing hash variant appears when a route group emits
    // multiple sizes, so use `startsWith` to cover both.
    pathname.startsWith("/opengraph-image") ||
    pathname.startsWith("/twitter-image") ||
    pathname.startsWith("/icon") ||
    pathname.startsWith("/apple-icon") ||
    pathname === "/robots.txt" ||
    pathname === "/sitemap.xml";

  if (isPublic) return NextResponse.next();

  // Token holds role/access_status from auth.ts callbacks.
  const userToken = req.auth?.user as
    | { role?: string; access_status?: string }
    | undefined;
  const role = userToken?.role ?? "user";
  const status = userToken?.access_status ?? "pending";
  const isAdmin = role === "admin";
  const isApproved = status === "approved";

  // ---- API routes: return JSON, never HTML redirect ------------------
  if (pathname.startsWith("/api/")) {
    if (!isLoggedIn) {
      return jsonError(401, "unauthorized");
    }
    // Access-request endpoints stay reachable for any logged-in user.
    if (pathname.startsWith("/api/access-request")) {
      return NextResponse.next();
    }
    // Admin-only API surface.
    if (pathname.startsWith("/api/admin/")) {
      if (!isAdmin) return jsonError(403, "admin only");
      return NextResponse.next();
    }
    // Everything else needs approval.
    if (!isApproved) return jsonError(403, "access pending");
    return NextResponse.next();
  }

  // ---- Page routes ---------------------------------------------------
  if (!isLoggedIn) {
    // Preserve the original path so a shared link like /stocks/017670.KS
    // routes back to the same page after sign-in, instead of dropping the
    // recipient on /dashboard. The login page reads `callbackUrl` and
    // passes it through to NextAuth's signIn() redirect.
    const loginUrl = new URL("/login", nextUrl);
    loginUrl.searchParams.set("callbackUrl", pathname + nextUrl.search);
    return NextResponse.redirect(loginUrl);
  }

  // Pending / rejected users get the /pending page only.
  if (!isApproved) {
    if (pathname === PENDING_PATH) return NextResponse.next();
    return NextResponse.redirect(new URL(PENDING_PATH, nextUrl));
  }

  // Approved users shouldn't see /pending; bounce them home.
  if (pathname === PENDING_PATH) {
    return NextResponse.redirect(new URL("/dashboard", nextUrl));
  }

  // Admin pages
  if (pathname.startsWith(ADMIN_PATH) && !isAdmin) {
    return NextResponse.redirect(new URL("/dashboard", nextUrl));
  }

  return NextResponse.next();
});

function jsonError(status: number, message: string): NextResponse {
  return new NextResponse(
    JSON.stringify({ error: message }),
    { status, headers: { "content-type": "application/json" } },
  );
}

export const config = {
  matcher: ["/((?!api/auth|_next/static|_next/image|favicon.ico).*)"],
};
