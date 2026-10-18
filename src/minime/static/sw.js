const CACHE_PREFIX = "minime-pwa-shell-";
const CACHE_NAME = `${CACHE_PREFIX}v2`;
const SHELL_ASSETS = [
  "/",
  "/dashboard",
  "/static/index.html",
  "/static/css/pwa.css",
  "/static/css/dashboard.css",
  "/static/css/tokens.css",
  "/static/css/layout.css",
  "/static/css/components.css",
  "/static/js/app.js",
  "/static/js/dashboard.js",
  "/static/js/desktop_pane_layout.js",
  "/static/js/state/store.js",
  "/static/js/services/api_client.js",
  "/static/js/services/control_plane_client.js",
  "/static/js/components/header.js",
  "/static/js/components/kpi_grid.js",
  "/static/js/components/attention_banner.js",
  "/static/js/components/queue_table.js",
  "/static/js/components/runs_table.js",
  "/static/js/components/pipeline_stepper.js",
  "/static/js/components/candidate_inspector.js",
  "/static/js/components/preview_panel.js",
  "/static/js/components/action_dialog.js",
  "/static/js/components/offline_banner.js",
  "/static/js/components/provider_grid.js",
  "/static/js/components/toast.js",
  "/static/manifest.webmanifest",
  "/static/icons/icon-192.png",
  "/static/icons/icon-192.svg",
  "/static/icons/icon-512.png",
  "/static/icons/icon-512.svg",
];
const CACHEABLE_PATHS = new Set(SHELL_ASSETS);

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(SHELL_ASSETS))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME)
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (
    request.method !== "GET" ||
    url.origin !== self.location.origin ||
    url.search !== "" ||
    !CACHEABLE_PATHS.has(url.pathname)
  ) {
    return;
  }

  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response.ok) {
          const copy = response.clone();
          event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.put(request, copy)));
        }
        return response;
      })
      .catch(async () => (await caches.match(request)) || Response.error()),
  );
});
