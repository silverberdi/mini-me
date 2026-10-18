const escapeHtml = (value) => String(value ?? "").replace(/[&<>\"']/g, (character) => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  "\"": "&quot;",
  "'": "&#39;",
}[character]));

export function renderQueue(root, items = [], onSelect = () => {}) {
  if (!root) return;
  if (!Array.isArray(items)) {
    root.innerHTML = '<p class="table-empty">Cola desconocida o no disponible.</p>';
    return;
  }
  if (!items.length) {
    root.innerHTML = '<p class="table-empty">No hay elementos en la cola observada.</p>';
    return;
  }

  root.innerHTML = items.map((item) => {
    const eligibility = item.admission_eligible === true
      ? "Elegibilidad informada por el servidor"
      : item.admission_eligible === false
        ? "No elegible según el servidor"
        : "Elegibilidad desconocida";
    const state = item.readiness_state || "UNKNOWN";
    const priority = item.priority_score === null || item.priority_score === undefined
      ? "No informada"
      : String(item.priority_score);
    const reason = item.blocked_reason || (item.unmet_readiness_reasons || []).join(" · ") || "Sin explicación informada";
    return `<article class="queue-item" data-project-id="${escapeHtml(item.project_id)}" data-change-name="${escapeHtml(item.change_name)}">
      <div class="queue-item-heading"><strong>${escapeHtml(item.github_issue_title || item.change_name)}</strong><span class="status-badge">${escapeHtml(state)}</span></div>
      <p>${escapeHtml(eligibility)} · Prioridad informada: ${escapeHtml(priority)}</p>
      <p class="queue-reason">${escapeHtml(reason)}</p>
      <button type="button" class="btn btn-secondary" data-queue-open>Ver trabajo</button>
    </article>`;
  }).join("");

  root.querySelectorAll("[data-queue-open]").forEach((button) => {
    button.addEventListener("click", () => {
      const item = button.closest("[data-project-id]");
      if (item) onSelect(item.dataset.projectId, item.dataset.changeName);
    });
  });
}
