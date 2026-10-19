export const json = async (url, options = {}) => {
  const method = String(options.method || "GET").toUpperCase();
  if (method !== "GET" && typeof navigator !== "undefined" && navigator.onLine === false) {
    throw Object.assign(new Error("Sin conexión; no se envió la acción."), { status: 503 });
  }
  const response = await fetch(url, {
    ...options,
    cache: "no-store",
    credentials: "same-origin",
    headers: { Accept: "application/json", ...(options.headers || {}) },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail = payload.detail || payload.error_message || payload.message;
    const error = new Error(detail || `${response.status} ${response.statusText}`);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return response.json();
};

export const api = {
  health: () => json("/health"),
  overview: () => json("/api/v1/dashboard/overview"),
  events: () => json("/api/v1/dashboard/events?limit=8"),
  queue: () => json("/api/v1/queue"),
  scheduler: () => json("/api/v1/scheduler/status"),
  runs: () => json("/api/v1/orchestration/runs"),
  providers: () => json("/providers/health"),
  detail: (project, change, runId) => json(`/api/v1/dashboard/changes/${encodeURIComponent(project)}/${encodeURIComponent(change)}${runId ? `?run_id=${encodeURIComponent(runId)}` : ""}`),
  actions: (runId) => json(`/api/v1/control-plane/actions/available?run_id=${encodeURIComponent(runId)}`),
  history: (runId) => json(`/api/v1/runs/${encodeURIComponent(runId)}/actions/history`),
  preview: (previewId) => json(`/api/v1/previews/${encodeURIComponent(previewId)}`),
  submitValidation: (body) => json("/api/v1/validations/submit", { method: "POST", body: JSON.stringify(body), headers: { "Content-Type": "application/json" } }),
  execute: (_runId, body) => json("/api/v1/control-plane/actions/execute", { method: "POST", body: JSON.stringify(body), headers: { "Content-Type": "application/json" } }),
};
