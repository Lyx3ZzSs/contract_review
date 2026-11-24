/* Custom frontend cache policy for the pinned labesign build.
 * Mutable web-apps always use the network (and normal HTTP cache semantics).
 * Never intercept document/download/callback requests or touch document caches.
 */
const build = new URL(self.registration.scope).pathname.split('/').filter(Boolean).at(-1);
const staticCache = 'document_editor_static_' + build;
const mutablePrefix = new URL('web-apps/', self.registration.scope).href;
const immutablePrefixes = ['sdkjs/', 'fonts/', 'sdkjs-plugins/', 'dictionaries/']
  .map(path => new URL(path, self.registration.scope).href);
const noStore = response => /(?:^|,)\s*no-store\s*(?:,|$)/i.test(response.headers.get('cache-control') || '');
self.addEventListener('install', event => event.waitUntil(self.skipWaiting()));
self.addEventListener('activate', event => event.waitUntil((async () => {
  // Migrate the old worker's cache without removing documents or other builds.
  const cache = await caches.open(staticCache);
  for (const request of await cache.keys()) {
    const response = await cache.match(request);
    if (request.url.startsWith(mutablePrefix) || (response && noStore(response))) await cache.delete(request);
  }
  await self.clients.claim();
})()));
self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET' || !immutablePrefixes.some(prefix => request.url.startsWith(prefix))) return;
  event.respondWith((async () => {
    const cache = await caches.open(staticCache);
    const cached = await cache.match(request);
    if (cached && !noStore(cached)) return cached;
    if (cached) await cache.delete(request);
    const response = await fetch(request);
    if (response.ok && ['basic', 'cors'].includes(response.type) && !response.redirected && !noStore(response)) {
      // A quota failure must not turn a successful resource request into an error.
      await cache.put(request, response.clone()).catch(() => {});
    }
    return response;
  })());
});
