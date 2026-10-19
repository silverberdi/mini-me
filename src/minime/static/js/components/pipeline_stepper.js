const escapeHtml = (value) => String(value ?? "").replace(/[&<>\"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
}[character]));
const ALLOWED_STATUS = new Set(["passed", "running", "failed", "blocked", "waiting", "not_started"]);
// Matches DashboardService._build_pipeline: UI renders authority-provided phases only.
export const PIPELINE_STAGES = ["readiness", "implementation", "checks", "review", "audit", "pr_merge"];
const ICONS = { readiness: "📋", implementation: "⚙️", checks: "🧪", review: "👥", audit: "🛡️", pr_merge: "🚀" };

export function renderPipelineStepper(container, phases, { stopOutcome = null } = {}) {
  if (!container) return;
  if (!Array.isArray(phases) || phases.length === 0) {
    container.replaceChildren();
    container.dataset.state = "UNKNOWN";
    return;
  }
  container.dataset.state = "OBSERVED";
  container.innerHTML = phases.map((phase, index) => {
    const status = ALLOWED_STATUS.has(phase.status) ? phase.status : "not_started";
    const lastObserved = stopOutcome === "CANCELLED" && status === "running";
    const label = escapeHtml(phase.display_name || phase.name || `Etapa ${index + 1}`);
    const visibleLabel = lastObserved ? `${label} · última etapa` : label;
    return `<div class="step-item ${lastObserved ? "stopped" : status}" data-stage="${escapeHtml(phase.name)}" data-phase-status="${status}"${lastObserved ? ' aria-label="Última etapa observada antes de la cancelación"' : ""}>
      <div class="step-bubble" title="${escapeHtml(phase.summary || "Sin resumen disponible")}">${ICONS[phase.name] || index + 1}</div>
      <div class="step-label">${visibleLabel}</div>
    </div>`;
  }).join("");
}
