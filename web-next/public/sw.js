// Thesauros service worker.
// 2026-05-28 — added stale-while-revalidate caching for the static asset
// bundle. Auth-gated API responses are NEVER cached (they'd leak across
// users on a shared device). Push handlers unchanged.

const CACHE = "thesauros-static-v1";

self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    // Drop any stale CACHE versions (so a deploy that bumps the suffix
    // clears the old bundle automatically on next activation).
    const keys = await caches.keys();
    await Promise.all(
      keys.filter((k) => k.startsWith("thesauros-static-") && k !== CACHE)
          .map((k) => caches.delete(k)),
    );
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  // GET only, same-origin only, no cookies (auth-gated content stays
  // bypass-fresh). Cache /_next/static (immutable hashed assets) + icons
  // + manifest. Anything else (HTML pages, /api/*, image upstreams) is
  // network-only.
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  const cacheable =
    url.pathname.startsWith("/_next/static/") ||
    url.pathname.startsWith("/icon-") ||
    url.pathname === "/manifest.webmanifest" ||
    url.pathname.endsWith(".png") ||
    url.pathname.endsWith(".svg") ||
    url.pathname.endsWith(".ico");
  if (!cacheable) return;
  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const hit = await cache.match(req);
    // Stale-while-revalidate: serve from cache immediately if present,
    // refresh in background so the next visit gets fresh.
    const fetchAndPut = fetch(req).then((res) => {
      if (res && res.status === 200) cache.put(req, res.clone());
      return res;
    }).catch(() => hit || Response.error());
    return hit || fetchAndPut;
  })());
});

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    data = { title: "Thesauros", body: event.data ? event.data.text() : "" };
  }
  const title = data.title || "Thesauros";
  const options = {
    body: data.body || "",
    tag: data.tag || "thesauros",
    data: { url: data.url || "/" },
    badge: "/icon-192.png",
    icon: "/icon-192.png",
    requireInteraction: data.severity === "critical",
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true })
      .then((wins) => {
        for (const w of wins) {
          if (w.url.includes(url) && "focus" in w) return w.focus();
        }
        if (self.clients.openWindow) return self.clients.openWindow(url);
      }),
  );
});
