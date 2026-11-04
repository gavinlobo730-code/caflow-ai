// v5 — a navigation that fails because the page could not be fetched shows /offline.html (a branded page that says it cannot reach PracticeSync and
// offers Try again) instead of the browser's own error page (POST-A-131). The worker cannot tell an offline device from an outage or a DNS failure, so the
// page does not claim to know which. EDITING offline.html ALONE DOES NOT REACH EXISTING INSTALLS: the page is stored when a worker installs, and a worker
// installs only when this file's bytes change, so change CACHE_NAME below whenever offline.html changes. Nothing else changes: data requests are never cached, and every branch still
// resolves to a real Response.
//
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
const CACHE_NAME = 'practicesync-v5';
const OFFLINE_PAGE = '/offline.html';
const STATIC_ASSETS = ['/login/'];

// Cloudflare Pages serves offline.html at /offline and REDIRECTS /offline.html to it, and a response marked `redirected` cannot answer a page
// navigation (the browser turns it into a network error). So the page is fetched once, and stored and served as a plain Response built from
// its bytes. Failing to store it must never fail the install: without it the fallback is the 503 it always was.
function plainPage(res) {
  return res.blob().then(b => new Response(b, { status: 200, headers: { 'Content-Type': 'text/html; charset=utf-8' } }));
}
function cacheOfflinePage(cache) {
  return fetch(OFFLINE_PAGE)
    .then(res => (res.ok ? plainPage(res).then(page => cache.put(OFFLINE_PAGE, page)) : undefined))
    .catch(() => undefined);
}

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(STATIC_ASSETS).then(() => cacheOfflinePage(c))));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  // Delete ALL previous caches (v1/v2/v3) so every client self-heals from
  // any prior version's bug the moment this version activates — no user
  // action needed. And give the offline page a second chance: if storing it at install failed (a transient error), nothing else would
  // ever retry it for this version.
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(() => caches.open(CACHE_NAME))
      .then(c => c.match(OFFLINE_PAGE).then(have => (have ? undefined : cacheOfflinePage(c))))
      .catch(() => undefined)
      .then(() => self.clients.claim())
  );
});

// Never lets respondWith() see a rejection or an undefined value: a cache
// miss (nothing was ever cached for this request, e.g. a never-visited page
// while offline) still resolves to a real Response instead of throwing.
function offlineFallback(request) {
  return caches.match(request).then(cached => {
    if (cached) return cached;
    // A page navigation that nothing cached gets the branded offline page; anything else (a script, an image, a data payload) keeps the
    // bare 503 it always had, because a page is not an acceptable answer to a request for a script.
    if (request.mode === 'navigate') {
      return caches.match(OFFLINE_PAGE).then(
        page => (page ? plainPage(page) : new Response(null, { status: 503, statusText: 'Offline' }))
      );
    }
    return new Response(null, { status: 503, statusText: 'Offline' });
  });
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
