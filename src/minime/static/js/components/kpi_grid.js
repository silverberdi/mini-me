export function renderKpis(root, metrics = {}) {
  if (!root) return;
  const values = {
    active: metrics.active_runs_count ?? metrics.active ?? 0,
    queue: metrics.queue_depth ?? metrics.queue ?? 0,
    ready: metrics.ready_count ?? metrics.ready ?? 0,
    blocked: metrics.blocked_count ?? metrics.blocked ?? metrics.attention_runs_count ?? 0,
  };
  root.querySelectorAll("[data-kpi]").forEach((node) => {
    const value = values[node.dataset.kpi];
    if (value !== undefined) node.textContent = String(value);
  });
  root.dataset.metrics = JSON.stringify(values);
}
