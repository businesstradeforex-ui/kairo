/* Kairo PWA: network first, cache only static shell. Never cache /api. */
const CACHE = "kairo-shell-1";
const SHELL = ["/app.css", "/app.js", "/ordres.js", "/settings.js", "/i18n.js", "/logo.svg", "/login.css", "/login.js", "/icon-192.png"];
self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/") || url.pathname.startsWith("/auth/")) return;
  event.respondWith(fetch(event.request).then((res) => {
    if (res.ok && SHELL.includes(url.pathname)) {
      const copy = res.clone();
      caches.open(CACHE).then((c) => c.put(event.request, copy));
    }
    return res;
  }).catch(() => caches.match(event.request)));
});
