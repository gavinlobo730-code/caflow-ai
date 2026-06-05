const CACHE_NAME = 'practicesync-v2';
const STATIC_ASSETS = ['/login/'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(STATIC_ASSETS)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  // Delete all previous caches including v1 so stale data is never served
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

  // Cache-first only for static assets (JS, CSS, images, fonts)
  const isStaticAsset =
    url.pathname.startsWith('/_next/static/') ||
    /\.(js|css|png|jpg|jpeg|svg|ico|woff|woff2)$/.test(url.pathname);

  if (isStaticAsset) {
    e.respondWith(
      caches.match(e.request).then(r => r || fetch(e.request).then(res => {
        if (res.ok) {
          caches.open(CACHE_NAME).then(c => c.put(e.request, res.clone()));
        }
        return res;
      }))
    );
    return;
  }

  // Everything else: network only
  e.respondWith(fetch(e.request));
});
