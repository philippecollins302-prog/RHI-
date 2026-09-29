// Le service worker de la tablette : la page s'ouvre même sans réseau.
//
// Réseau d'abord, cache ensuite : en ligne, chaque ouverture prend la
// dernière version (pas de version à monter à la main, pas de tablette
// coincée sur une vieille page) ; hors ligne, la dernière vue sert. Les
// appels /api/ ne passent jamais par ce cache : la file des gestes, dans
// terrain.js, s'en charge.
const CACHE = 'rhi-coquille';
const SHELL = ['/', '/app.css', '/commun.js', '/terrain.js', '/manifest.json'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/')) return;
  e.respondWith(
    fetch(e.request)
      .then((r) => {
        if (r.ok) { const copie = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, copie)); }
        return r;
      })
      // Hors ligne : la copie gardée ; à défaut, la page de la tablette —
      // mais seulement pour elle (le bureau hors ligne ne doit pas s'ouvrir
      // en tablette).
      .catch(() => caches.match(e.request).then((r) => r ||
        (e.request.mode === 'navigate' && url.pathname === '/' ? caches.match('/') : Response.error()))));
});
