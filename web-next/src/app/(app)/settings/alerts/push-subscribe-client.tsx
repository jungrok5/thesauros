"use client";

/**
 * PWA push-subscription UI.
 *
 * - Detects browser support for `serviceWorker` + `PushManager`.
 * - Reads `NEXT_PUBLIC_VAPID_PUBLIC_KEY`; if absent, shows a "not configured"
 *   notice so the page still renders cleanly.
 * - Registers `/sw.js` (in /public), subscribes with the VAPID public key,
 *   and POSTs the subscription to /api/push/subscribe.
 */
import { useEffect, useState } from "react";

const VAPID = process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY ?? "";

function urlBase64ToUint8Array(base64String: string): Uint8Array<ArrayBuffer> {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const buffer = new ArrayBuffer(raw.length);
  const out = new Uint8Array(buffer);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

function detectSupport(): boolean | null {
  if (typeof window === "undefined") return null;
  return "serviceWorker" in navigator && "PushManager" in window;
}

export function PushSubscribe() {
  const [supported] = useState<boolean | null>(detectSupport);
  const [subscribed, setSubscribed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!supported) return;
    let cancelled = false;
    (async () => {
      try {
        const reg = await navigator.serviceWorker.getRegistration("/sw.js");
        const sub = await reg?.pushManager.getSubscription();
        if (!cancelled) setSubscribed(!!sub);
      } catch {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [supported]);

  async function subscribe() {
    setBusy(true);
    setError(null);
    try {
      if (!VAPID) throw new Error("VAPID 키 미설정 (서버 환경변수 추가 필요)");
      const reg =
        (await navigator.serviceWorker.getRegistration("/sw.js")) ??
        (await navigator.serviceWorker.register("/sw.js"));
      const perm = await Notification.requestPermission();
      if (perm !== "granted") throw new Error("알림 권한이 거부됨");
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(VAPID),
      });
      const r = await fetch("/api/push/subscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(sub.toJSON()),
      });
      if (!r.ok) throw new Error(`subscribe ${r.status}`);
      setSubscribed(true);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  async function unsubscribe() {
    setBusy(true);
    setError(null);
    try {
      const reg = await navigator.serviceWorker.getRegistration("/sw.js");
      const sub = await reg?.pushManager.getSubscription();
      if (sub) {
        await fetch("/api/push/subscribe", {
          method: "DELETE",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ endpoint: sub.endpoint }),
        }).catch(() => null);
        await sub.unsubscribe();
      }
      setSubscribed(false);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  if (supported === null) return null;

  if (!supported) {
    return (
      <div className="rounded-lg border border-border bg-card p-3 text-xs text-muted-foreground">
        브라우저가 PWA 푸시 알림을 지원하지 않습니다.
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-2 text-sm">
      <div className="font-medium">📱 브라우저 푸시 (PWA)</div>
      <p className="text-xs text-muted-foreground">
        텔레그램과 별개로, 이 브라우저/디바이스로 직접 푸시 알림을 받습니다.
        설치된 PWA 에서는 백그라운드에서도 동작합니다.
      </p>
      {subscribed ? (
        <button
          type="button"
          onClick={unsubscribe}
          disabled={busy}
          className="px-3 py-1.5 rounded border border-rose-500/40 text-xs text-rose-700 dark:text-rose-300 hover:bg-rose-500/10 disabled:opacity-50"
        >
          {busy ? "..." : "푸시 구독 해제"}
        </button>
      ) : (
        <button
          type="button"
          onClick={subscribe}
          disabled={busy}
          className="px-3 py-1.5 rounded bg-foreground text-background text-xs font-medium hover:opacity-90 disabled:opacity-50"
        >
          {busy ? "..." : "푸시 알림 켜기"}
        </button>
      )}
      {error && <div className="text-xs text-rose-600">{error}</div>}
    </div>
  );
}
