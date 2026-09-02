export const json = async (url, options = {}) => {
  const response = await fetch(url, {
    ...options,
    headers: { Accept: "application/json", ...(options.headers || {}) },
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
};

export const api = {
  overview: () => json("/api/v1/dashboard/overview"),
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
