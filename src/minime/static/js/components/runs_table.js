export const RUN_FILTERS = ["ALL", "IN_PROGRESS", "NEEDS_HUMAN", "FAILED", "COMPLETED"];
export const filterRuns = (runs = [], status = "ALL") => status === "ALL" ? runs : runs.filter(run => (run.status || "").toUpperCase() === status);
export function renderRuns(root, runs = [], status = "ALL", onSelect = () => {}) {
  if (!root) return;
  const visible = filterRuns(runs, status);
  root.innerHTML = visible.length ? visible.map((run) => `<button type="button" class="run-row" data-run-id="${run.run_id || run.id}"><span>${run.change_name || "—"}</span><span class="status-badge">${run.status || "UNKNOWN"}</span><span>${run.current_stage || run.stage || "—"}</span></button>`).join("") : '<p class="table-empty">No runs match this filter.</p>';
  root.querySelectorAll("[data-run-id]").forEach((row) => row.addEventListener("click", () => onSelect(row.dataset.runId)));
}
