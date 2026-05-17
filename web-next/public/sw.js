// Minimal Thesauros service worker.
// Goals: install + accept push events + show notification. No caching strategy
// yet — Next.js already serves with strong ETags, and we want fresh data.

self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
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
