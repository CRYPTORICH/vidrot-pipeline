const CACHE = "vidrot-shell-6";
// Paths are relative to the service worker, so the app works at / or under a prefix like /vidrot/.
const BASE = new URL(self.registration.scope).pathname.replace(/\/$/, "");
const SHELL = ["./", "static/app.css", "static/app.js", "manifest.webmanifest", "icons/icon-192.png", "icons/icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;
  const path = BASE && url.pathname.startsWith(BASE) ? url.pathname.slice(BASE.length) : url.pathname;
  if (path.startsWith("/api") || path.startsWith("/media") || path === "/healthz") return;
  if (event.request.method !== "GET") return;
  event.respondWith(
    fetch(event.request).then((response) => {
      if (response.ok) {
        const copy = response.clone();
        caches.open(CACHE).then((cache) => cache.put(event.request, copy));
      }
      return response;
    }).catch(() => caches.match(event.request).then((hit) => hit || caches.match("./")))
  );
});

self.addEventListener("push", (event) => {
  let payload = { title: "vidrot", body: "The job updated." };
  try {
    payload = event.data ? event.data.json() : payload;
  } catch (err) {
    payload.body = event.data ? event.data.text() : payload.body;
  }
  event.waitUntil(self.registration.showNotification(payload.title || "vidrot", {
    body: payload.body || "",
    icon: "icons/icon-192.png",
    badge: "icons/icon-192.png",
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
    if (clients.length) return clients[0].focus();
    return self.clients.openWindow("./");
  }));
});
