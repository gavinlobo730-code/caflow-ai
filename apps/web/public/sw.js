// Basic cache-first service worker for offline support
const CACHE_NAME = 'caflow-v1';
const STATIC_ASSETS = ['/', '/login'];
self.addEventListener('install', e => e.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(STATIC_ASSETS))));
self.addEventListener('fetch', e => e.respondWith(caches.match(e.request).then(r => r || fetch(e.request))));
