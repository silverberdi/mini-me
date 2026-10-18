function countOrUnknown(value) {
  return Number.isInteger(value) && value >= 0 ? String(value) : "—";
}

export function renderKpis(root, metrics = {}) {
  if (!root) return;
  const values = {
    active: countOrUnknown(metrics.active_runs_count),
    attention: countOrUnknown(metrics.attention_runs_count),
    completed: countOrUnknown(metrics.recent_completions_count),
  };
  root.querySelectorAll("[data-kpi]").forEach((node) => {
    const value = values[node.dataset.kpi];
    if (value !== undefined) node.textContent = value;
  });
  root.dataset.metrics = JSON.stringify(values);
}
