const CACHE_PREFIX = "minime-pwa-shell-";
const CACHE_NAME = `${CACHE_PREFIX}f7`; // f5 baseline bump
const SHELL_ASSETS = [
  "dashboard.js"
];
const CACHEABLE_PATHS = new Set(SHELL_ASSETS);

self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.startsWith(CACHE_PREFIX))
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.registration.unregister())
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", () => {
  // Pass through to network
});

