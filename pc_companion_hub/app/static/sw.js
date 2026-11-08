// Minimaler Service Worker: App-Shell cachen (nur HTTPS/localhost aktiv). API und WS nie cachen.
const CACHE = "pcc-shell-v6";
const SHELL = ["./", "index.html", "style.css", "app.js", "actions.js", "upload.js", "manifest.webmanifest", "icon.svg"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k.startsWith("pcc-shell") && k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
// Android „Teilen“: Dateien in den Cache legen, die Seite lädt sie hoch (sie kennt das Token).
async function handleShare(request) {
  const scope = self.registration.scope;
  const files = (await request.formData()).getAll("files").filter(f => f && typeof f !== "string");
  const cache = await caches.open("pcc-share");
  let i = 0;
  for (const f of files) {
    await cache.put(
      new Request(scope + "shared/" + Date.now() + "-" + i++),
      new Response(f, { headers: { "X-Filename": encodeURIComponent(f.name), "Content-Type": f.type || "application/octet-stream" } }),
    );
  }
  return Response.redirect(scope + "?share=" + files.length, 303);
}

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method === "POST" && url.pathname === new URL("share", self.registration.scope).pathname) {
    e.respondWith(handleShare(e.request));
    return;
  }
  if (e.request.method !== "GET" || url.pathname.includes("/api/") || url.pathname.endsWith("/ws")) return;
  e.respondWith(fetch(e.request).then(r => {
    const copy = r.clone();
    caches.open(CACHE).then(c => c.put(e.request, copy));
    return r;
  }).catch(() => caches.match(e.request)));
});
