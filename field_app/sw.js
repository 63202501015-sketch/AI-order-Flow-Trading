// Offline cache: เปิดแอปได้แม้ไม่มีสัญญาณ (network-first, fallback cache)
const C = "wsm-v2";
const A = ["./", "index.html", "app.js", "config.js", "master.json", "field_map.jpg", "manifest.json", "icon-192.png", "icon-512.png"];
self.addEventListener("install", e => e.waitUntil(caches.open(C).then(c => c.addAll(A)).then(() => self.skipWaiting())));
self.addEventListener("activate", e => e.waitUntil(
  caches.keys().then(ks => Promise.all(ks.filter(k => k !== C).map(k => caches.delete(k)))).then(() => self.clients.claim())
));
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin) return; // ไม่แคชคำขอไป Google
  e.respondWith(
    fetch(e.request).then(r => {
      const x = r.clone();
      caches.open(C).then(c => c.put(e.request, x));
      return r;
    }).catch(() => caches.match(e.request, { ignoreSearch: true }))
  );
});
