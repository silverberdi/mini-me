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
  "/static/js/services/api_client.js",
  "/static/js/services/session_controller.js",
  "/static/js/services/control_plane_client.js",
  "/static/js/controllers/action_controller.js",
  "/static/js/controllers/detail_telemetry_controller.js",
  "/static/js/controllers/detail_view_controller.js",
  "/static/js/controllers/execution_view_controller.js",
  "/static/js/controllers/preview_controller.js",
  "/static/js/controllers/backlog_controller.js",
  "/static/js/controllers/lifecycle_controller.js",
  "/static/js/controllers/projects_controller.js",
  "/static/js/controllers/navigation_controller.js",
  "/static/js/components/kpi_grid.js",
  "/static/js/components/queue_table.js",
  "/static/js/components/pipeline_stepper.js",
  "/static/js/components/action_dialog.js",
  "/static/js/components/offline_banner.js",
  "/static/js/components/provider_grid.js",
  "/static/js/components/theme_controller.js",
  "/static/js/views/operational_panels_view.js",
  "/static/js/views/overview_view.js",
  "/static/js/views/projects_view.js",
  "/static/js/views/backlog_view.js",
  "/static/js/views/evidence_views.js",
  "/static/js/views/detail_telemetry_views.js",
  "/static/js/views/preview_view.js",
  "/static/js/views/github_timeline_views.js",
  "/static/js/views/runs_view.js",
  "/static/js/views/status_view.js",
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
