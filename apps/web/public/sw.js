// v4 — fixes a hard navigation failure: v3's final catch-all branch
// (isDataRequest/navigate/isStaticAsset all false — this is where every
// Next.js App Router client-side route transition's background RSC/".txt"
// payload fetch lands, since ".txt" isn't a recognized static-asset
// extension) called fetch(e.request) with NO .catch(). Whenever that fetch
// was interrupted — verified in production: a raw window.history.replaceState
// call elsewhere on the page, racing router.push(), was aborting the
// in-flight request — the rejection went uncaught, and per the Service
// Worker spec an uncaught respondWith() rejection is reported to the browser
// as a hard network-error response, not a retryable failure. Next's router
// then silently aborted the whole transition, leaving the user exactly where
// they started (looked like "clicking Edit does nothing"). Every branch here
// now guarantees respondWith() always resolves to a real Response, never an
// uncaught rejection and never `undefined` (caches.match() misses return
// undefined, which respondWith() can't accept either — offlineFallback()
// below covers that gap too, pre-existing in every branch since v2/v3).
const CACHE_NAME = 'practicesync-v4';
const STATIC_ASSETS = ['/login/'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(STATIC_ASSETS)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  // Delete ALL previous caches (v1/v2/v3) so every client self-heals from
  // any prior version's bug the moment this version activates — no user
  // action needed.
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// Never lets respondWith() see a rejection or an undefined value: a cache
// miss (nothing was ever cached for this request, e.g. a never-visited page
// while offline) still resolves to a real Response instead of throwing.
function offlineFallback(request) {
  return caches.match(request).then(
    cached => cached || new Response(null, { status: 503, statusText: 'Offline' })
  );
}

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
    e.respondWith(fetch(e.request).catch(() => offlineFallback(e.request)));
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
      }).catch(() => offlineFallback(e.request))
    );
    return;
  }

  // Everything else — including every App Router client-side transition's
  // background RSC/".txt" data fetch (Next never uses request.mode:'navigate'
  // for these; a script-initiated fetch() can't carry that browser-reserved
  // mode) — network only, but NEVER left uncaught: a rejection here (an
  // aborted/interrupted request, a transient network blip, anything) now
  // resolves to a graceful fallback instead of killing the page transition.
  e.respondWith(fetch(e.request).catch(() => offlineFallback(e.request)));
});
