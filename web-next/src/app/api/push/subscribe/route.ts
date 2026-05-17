/**
 * POST   /api/push/subscribe   — store a PushSubscription for current user
 * DELETE /api/push/subscribe   — remove one (body: { endpoint })
 *
 * Payload matches `PushSubscription.toJSON()`:
 *   { endpoint: string, keys: { p256dh: string, auth: string } }
 *
 * The Python worker reads `push_subscriptions` and uses pywebpush to deliver.
 */
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { ensureUserId, getServerClient } from "@/lib/supabase";

export const dynamic = "force-dynamic";

/**
 * Web-Push endpoints live on a handful of vendor domains. Allowlist
 * the protocol + parse with WHATWG URL so we don't accept arbitrary
 * `https://...` strings (even ones containing percent-encoded nulls).
 */
const PUSH_HOST_ALLOWLIST = [
  /\.googleapis\.com$/,                      // FCM (Chrome, Edge, Brave, Opera)
  /\.mozilla\.com$/,                         // autopush.services.mozilla.com etc.
  /\.push\.services\.mozilla\.com$/,
  /\.windows\.com$/,                         // legacy Edge WNS
  /\.notify\.windows\.com$/,
  /\.push\.apple\.com$/,                     // Safari (WebPush)
];

function isAllowedPushEndpoint(raw: string): boolean {
  let u: URL;
  try {
    u = new URL(raw);
  } catch {
    return false;
  }
  if (u.protocol !== "https:") return false;
  return PUSH_HOST_ALLOWLIST.some((re) => re.test(u.hostname));
}

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
  if (!userId) return NextResponse.json({ error: "unauthorized" }, { status: 401 });

  const body = await req.json().catch(() => ({}));
  const endpoint = String(body.endpoint ?? "");
  const p256dh = String(body.keys?.p256dh ?? "");
  const authKey = String(body.keys?.auth ?? "");
  if (!isAllowedPushEndpoint(endpoint) || !p256dh || !authKey) {
    return NextResponse.json({ error: "invalid payload" }, { status: 400 });
  }
  const userAgent = (req.headers.get("user-agent") ?? "").slice(0, 255);

  const sb = getServerClient();
  // endpoint is UNIQUE — onConflict avoids dupes if user re-subscribes
  const { error } = await sb
    .from("push_subscriptions")
    .upsert(
      { user_id: userId, endpoint, p256dh, auth: authKey, user_agent: userAgent },
      { onConflict: "endpoint" },
    );
  if (error) {
    console.error("push subscribe:", error.message);
    return NextResponse.json({ error: "db error" }, { status: 500 });
  }
  return NextResponse.json({ ok: true });
}

export async function DELETE(req: NextRequest) {
  const userId = await currentUserId();
  if (!userId) return NextResponse.json({ error: "unauthorized" }, { status: 401 });

  const body = await req.json().catch(() => ({}));
  const endpoint = String(body.endpoint ?? "");
  if (!isAllowedPushEndpoint(endpoint)) {
    return NextResponse.json({ error: "invalid payload" }, { status: 400 });
  }
  const sb = getServerClient();
  const { error } = await sb
    .from("push_subscriptions")
    .delete()
    .eq("user_id", userId)
    .eq("endpoint", endpoint);
  if (error) {
    console.error("push unsubscribe:", error.message);
    return NextResponse.json({ error: "db error" }, { status: 500 });
  }
  return NextResponse.json({ ok: true });
}
