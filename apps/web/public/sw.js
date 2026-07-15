// v3 — fixes the stale-deploy bug: v2 served /_next/static/ chunks CACHE-FIRST
// forever, so a browser that had visited a page kept executing that page's OLD
// JavaScript after every new deployment (hard reloads and DevTools' "Disable
// cache" don't touch SW Cache Storage). Verified in production: a browser was
// loading page-13acab… + webpack-c73cbe9… — chunks that no longer existed in
// the live build — weeks of fixes invisible on previously-visited pages while
// never-visited pages showed current code. Content-hashed /_next/static files
// are already served immutable by Cloudflare's HTTP cache, so the SW gains
// nothing by preferring its own copy; network-first keeps the offline
// fallback without ever preferring a stale copy while online.
const CACHE_NAME = 'practicesync-v3';
const STATIC_ASSETS = ['/login/'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(STATIC_ASSETS)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  // Delete ALL previous caches (v1/v2) so every client self-heals from the
  // stale-chunk bug the moment this version activates — no user action needed.
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // Never cache Supabase API calls, Render backend calls, or any non-GET
  const isDataRequest =
    url.hostname.includes('supabase.co') ||
    url.hostname.includes('onrender.com') ||
    e.request.method !== 'GET';

  if (isDataRequest) {
    e.respondWith(fetch(e.request));
    return;
  }

  // Network-first for HTML navigation
  if (e.request.mode === 'navigate') {
    e.respondWith(
      fetch(e.request).catch(() => caches.match(e.request))
    );
    return;
  }

  // Static assets (JS, CSS, images, fonts): NETWORK-FIRST with cache fallback.
  // Fresh copies are re-cached on every successful fetch so the fallback stays
  // as current as the last time the user was online; the cached copy is only
  // ever used when the network itself fails (offline), never in preference to
  // the live deployment.
  const isStaticAsset =
    url.pathname.startsWith('/_next/static/') ||
    /\.(js|css|png|jpg|jpeg|svg|ico|woff|woff2)$/.test(url.pathname);

  if (isStaticAsset) {
    e.respondWith(
      fetch(e.request).then(res => {
        if (res.ok) {
          const resClone = res.clone();
          caches.open(CACHE_NAME).then(c => c.put(e.request, resClone));
        }
        return res;
      }).catch(() => caches.match(e.request))
    );
    return;
  }

  // Everything else: network only
  e.respondWith(fetch(e.request));
});
