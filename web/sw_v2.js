const CACHE_NAME = 'memex-pwa-v1';
const ASSETS_TO_CACHE = [
    '/',
    '/index.html', // Might be served as / by backend
    '/static/css/style.css',
    '/static/js/app.js',
    '/static/js/audio_manager.js',
    // '/static/assets/favicon.ico', // Removed: File does not exist, causing SW failure
    // External assets
    'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap',
    'https://fonts.googleapis.com/icon?family=Material+Icons',
    'https://cdn.jsdelivr.net/npm/vue@3.2.47/dist/vue.global.prod.js',
    'https://cdn.jsdelivr.net/npm/axios/dist/axios.min.js',
    'https://cdn.jsdelivr.net/npm/marked/marked.min.js'
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            console.log('[Service Worker] Caching static assets');
            // Use addAll with error handling or individual fetch to avoid one failure breaking all
            return cache.addAll(ASSETS_TO_CACHE).catch(err => {
                console.warn('[Service Worker] Failed to cache some assets', err);
            });
        })
    );
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames.map((cacheName) => {
                    if (cacheName !== CACHE_NAME) {
                        return caches.delete(cacheName);
                    }
                })
            );
        })
    );
    self.clients.claim();
});

self.addEventListener('fetch', (event) => {
    // Always network for API
    if (event.request.url.includes('/api/')) {
        return;
    }

    // Stale-While-Revalidate for others
    event.respondWith(
        caches.match(event.request).then((cachedResponse) => {
            const fetchPromise = fetch(event.request).then((networkResponse) => {
                // Update cache
                if (networkResponse && networkResponse.status === 200 && networkResponse.type === 'basic') {
                    const responseToCache = networkResponse.clone();
                    caches.open(CACHE_NAME).then((cache) => {
                        cache.put(event.request, responseToCache);
                    });
                }
                return networkResponse;
            }).catch(() => {
                // Offline fallback if needed
            });

            return cachedResponse || fetchPromise;
        })
    );
});
