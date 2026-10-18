export function renderBacklogTable({
  root,
  items,
  filter,
  query,
  selectedItem,
  escapeHtml,
  getStatusBadgeClass,
}) {
  if (!root) return;
  let filtered = items;
  if (filter !== "ALL") {
    filtered = filtered.filter((item) => {
      if (filter === "NEEDS_HUMAN") return item.status === "NEEDS_HUMAN";
      if (filter === "READY") return item.status === "READY";
      if (filter === "RUNNING") return item.status === "RUNNING";
      if (filter === "COMPLETED") return item.status === "COMPLETED";
      if (filter === "BACKLOG") return ["BACKLOG", "DRAFT", "PREPARING"].includes(item.status);
      return true;
    });
  }

  if (query) {
    filtered = filtered.filter((item) =>
      item.title.toLowerCase().includes(query)
      || item.item_key.toLowerCase().includes(query)
      || (item.description && item.description.toLowerCase().includes(query)),
    );
  }

  if (!filtered?.length) {
    root.innerHTML = '<tr><td colspan="6" class="table-empty">No hay trabajo que coincida con el filtro actual.</td></tr>';
    return;
  }

  root.innerHTML = filtered.map((item) => {
    const isSelected = selectedItem?.item_key === item.item_key;
    const isReady = item.status === "READY";
    const priorityClass = getPriorityBadgeClass(item.priority);

    return `
      <tr class="clickable-row ${isSelected ? "selected-row" : ""}" data-item-key="${escapeHtml(item.item_key)}">
        <td><span class="badge ${getStatusBadgeClass(item.status)}">${escapeHtml(item.status)}</span></td>
        <td>
          <div class="bk-title font-semibold">${escapeHtml(item.title)}</div>
          <div class="bk-key font-mono text-muted text-xs">${escapeHtml(item.item_key)}</div>
        </td>
        <td><span class="badge ${priorityClass}">${escapeHtml(item.priority || "DESCONOCIDA")}</span></td>
        <td><span class="badge badge-discovered">${escapeHtml(item.source || "DESCONOCIDO")}</span></td>
        <td><span class="dor-status-pill ${isReady ? "ready" : (item.status === "NEEDS_HUMAN" ? "needs-human" : "not-ready")}">${isReady ? "READY" : (item.status === "NEEDS_HUMAN" ? "REQUIERE ATENCIÓN" : "NO LISTO")}</span></td>
        <td><div class="action-btn-group">
          ${!isReady && item.status !== "RUNNING" && item.status !== "COMPLETED" ? `<button type="button" class="btn btn-secondary btn-xs" data-backlog-action="prepare" data-item-key="${escapeHtml(item.item_key)}">Preparar</button>` : ""}
          ${isReady ? `<button type="button" class="btn btn-primary btn-xs" data-backlog-action="start" data-item-key="${escapeHtml(item.item_key)}">🚀 Iniciar</button>` : ""}
        </div></td>
      </tr>`;
  }).join("");
}

function getPriorityBadgeClass(priority) {
  return priority === "CRITICAL" ? "badge-danger"
    : priority === "HIGH" ? "badge-warning"
      : priority === "LOW" ? "badge-muted" : "badge-info";
}

export function renderBacklogDetail({
  item,
  elements,
  escapeHtml,
  sanitizeUrl,
  renderMarkdownText,
  getStatusBadgeClass,
}) {
  const { placeholder, content } = elements;
  if (!item) {
    if (placeholder) placeholder.style.display = "flex";
    if (content) content.style.display = "none";
    return;
  }
  if (placeholder) placeholder.style.display = "none";
  if (content) content.style.display = "block";

  const setText = (node, value) => { if (node) node.textContent = value; };
  setText(elements.title, item.title);
  setText(elements.key, item.item_key);
  setText(elements.source, item.source || "DESCONOCIDO");
  setText(elements.readiness, item.status === "READY" ? "READY" : item.status === "NEEDS_HUMAN" ? "NEEDS_HUMAN" : "NOT_READY");
  if (elements.status) {
    elements.status.textContent = item.status;
    elements.status.className = `badge ${getStatusBadgeClass(item.status)}`;
  }
  if (elements.priority) {
    elements.priority.textContent = item.priority || "DESCONOCIDA";
    elements.priority.className = `badge ${getPriorityBadgeClass(item.priority)}`;
  }
  if (elements.startButton) {
    elements.startButton.disabled = item.status !== "READY";
    elements.startButton.textContent = item.status === "RUNNING" ? "⚡ Running..." : "🚀 Start Work";
  }

  const questions = item.human_questions?.length ? item.human_questions : [
    "El detalle de la información requerida no está disponible.",
  ];
  if (elements.needsHumanCard) {
    const hasQuestions = item.status === "NEEDS_HUMAN" || item.human_questions?.length > 0;
    elements.needsHumanCard.style.display = hasQuestions ? "block" : "none";
    if (elements.answerTarget) elements.answerTarget.value = item.human_questions?.[0] || "";
    if (hasQuestions && elements.humanQuestionsList) {
      elements.humanQuestionsList.innerHTML = questions.map((question) => `<div class="question-item"><span class="question-icon">❓</span><span class="question-text">${escapeHtml(question)}</span></div>`).join("");
    }
  }
  if (elements.description) elements.description.innerHTML = renderMarkdownText(item.description || "Descripción no disponible.");
  if (elements.criteria) {
    elements.criteria.innerHTML = item.acceptance_criteria?.length
      ? item.acceptance_criteria.map((criterion) => `<li class="criteria-item">✓ ${escapeHtml(criterion)}</li>`).join("")
      : '<li class="text-muted">Criterios de aceptación no disponibles.</li>';
  }

  const checklist = item.readiness_checklist || {};
  const isReady = item.status === "READY" || checklist.is_ready === true;
  const isNotReady = checklist.is_ready === false || Object.values(checklist).some((value) => value === false);
  if (elements.dorOverall) {
    const label = isReady ? "LISTO PARA ADMISIÓN" : item.status === "NEEDS_HUMAN" ? "REQUIERE ATENCIÓN" : isNotReady ? "NO LISTO" : "ESTADO DESCONOCIDO";
    elements.dorOverall.textContent = label;
    elements.dorOverall.className = `dor-status-pill ${isReady ? "ready" : item.status === "NEEDS_HUMAN" ? "needs-human" : isNotReady ? "not-ready" : "unknown"}`;
  }
  if (elements.dorGrid) {
    const rules = [
      ["repo_binding_valid", "Vinculación de repositorio válida", checklist.repo_binding_valid],
      ["item_identity_valid", "Identidad del trabajo válida", checklist.item_identity_valid],
      ["github_issue_linked", "Issue de GitHub vinculado", checklist.github_issue_linked],
      ["github_project_linked", "Elemento de proyecto vinculado", checklist.github_project_linked],
      ["openspec_valid", "Artefactos OpenSpec válidos", checklist.openspec_valid],
      ["acceptance_criteria_present", "Criterios de aceptación definidos", checklist.acceptance_criteria_present],
      ["dependencies_resolved", "Dependencias resueltas", checklist.dependencies_resolved],
      ["security_requirements_identified", "Requisitos de seguridad identificados", checklist.security_requirements_identified],
      ["ux_requirements_identified", "Requisitos UX/preview identificados", checklist.ux_requirements_identified],
      ["no_unresolved_ambiguity", "Sin ambigüedad pendiente", checklist.no_unresolved_ambiguity],
      ["definition_of_ready_met", "Definición de Ready satisfecha", item.status === "READY" ? true : checklist.definition_of_ready_met],
    ];
    elements.dorGrid.innerHTML = rules.map(([, label, valid]) => {
      const state = valid === true ? "pass" : valid === false ? "fail" : "unknown";
      const icon = valid === true ? "✓" : valid === false ? "✗" : "?";
      return `<div class="dor-item dor-${state}" data-state="${state}"><span class="dor-icon">${icon}</span><span class="dor-label">${escapeHtml(label)}</span></div>`;
    }).join("");
  }

  if (elements.openSpec) elements.openSpec.innerHTML = item.openspec_change_name
    ? `<span class="text-success font-mono">openspec/changes/${escapeHtml(item.openspec_change_name)}</span>`
    : '<span class="text-muted">Aún no generado</span>';
  if (elements.issue) elements.issue.innerHTML = item.github_issue_url
    ? `<a href="${sanitizeUrl(item.github_issue_url)}" target="_blank" rel="noopener noreferrer" class="text-primary font-mono">#${item.github_issue_number} ↗</a>`
    : item.github_issue_number ? `#${item.github_issue_number}` : '<span class="text-muted">Aún no vinculado</span>';
  if (elements.projectItem) elements.projectItem.innerHTML = item.github_project_item_id
    ? `<span class="text-success font-mono">${escapeHtml(item.github_project_item_id)}</span>` : '<span class="text-muted">Aún no sincronizado</span>';
  if (elements.run) elements.run.innerHTML = item.active_orchestration_run_id
    ? `<button type="button" class="text-primary font-mono btn-link" data-open-run="${escapeHtml(item.active_orchestration_run_id)}">${escapeHtml(item.active_orchestration_run_id)} ↗</button>`
    : '<span class="text-muted">Sin ejecución activa</span>';
}
