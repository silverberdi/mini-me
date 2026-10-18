const escapeHtml = (value) => String(value ?? "").replace(/[&<>\"']/g, (character) => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  "\"": "&quot;",
  "'": "&#39;",
}[character]));

function projectStatusBadge(status) {
  switch (status) {
    case "READY_FOR_WORK": return '<span class="badge badge-ready">LISTO PARA TRABAJAR</span>';
    case "CONTEXT_INCOMPLETE": return '<span class="badge badge-waiting">CONTEXTO INCOMPLETO</span>';
    case "BINDING": return '<span class="badge badge-running">VINCULANDO</span>';
    case "BLOCKED": return '<span class="badge badge-failed">BLOQUEADO</span>';
    default: return '<span class="badge badge-not-ready">DESCONOCIDO</span>';
  }
}

export function renderProjectSelect(root, projects, selectedProjectId) {
  if (!root) return selectedProjectId;
  const projectId = (project) => project.project_id ?? project.id;
  const selected = projects.some((project) => projectId(project) === selectedProjectId)
    ? selectedProjectId : projectId(projects[0] || {}) || null;
  root.innerHTML = '<option value="">Selecciona un proyecto…</option>' + projects.map((project) => `
    <option value="${escapeHtml(projectId(project))}" ${projectId(project) === selected ? "selected" : ""}>${escapeHtml(project.display_name || project.name || projectId(project))}</option>
  `).join("");
  root.value = selected || "";
  return selected;
}

export function renderProjectsGrid(root, projects, currentProjectId) {
  if (!root) return;
  if (!projects.length) {
    root.innerHTML = '<p class="text-muted">No hay proyectos registrados. Registra uno para vincular su repositorio.</p>';
    return;
  }
  const projectId = (project) => project.project_id ?? project.id;
  root.innerHTML = projects.map((project) => `
    <div class="project-card ${projectId(project) === currentProjectId ? "active-project-card" : ""}">
      <div class="project-card-header"><div class="project-card-title-group">
        <h3 class="project-name">${escapeHtml(project.display_name || project.name || projectId(project))}</h3>
        <span class="project-id font-mono text-muted text-xs">ID: ${escapeHtml(projectId(project))}</span>
      </div>${projectStatusBadge(project.onboarding_status)}</div>
      <div class="project-card-meta">
        <div class="meta-row"><strong>Repositorio:</strong> <span class="font-mono">${escapeHtml(project.repository || "DESCONOCIDO")}</span></div>
        <div class="meta-row"><strong>Rama base:</strong> <span class="font-mono">${escapeHtml(project.base_branch || "DESCONOCIDA")}</span></div>
        <div class="meta-row"><strong>Ruta OpenSpec:</strong> <span class="font-mono">${escapeHtml(project.openspec_path || "DESCONOCIDA")}</span></div>
        <div class="meta-row"><strong>Hoja de ruta:</strong> <span class="font-mono">${escapeHtml(project.roadmap_path || "DESCONOCIDA")}</span></div>
      </div>
      <div class="project-card-actions">
        <button type="button" class="btn btn-secondary btn-sm" data-project-action="inspect" data-project-id="${escapeHtml(projectId(project))}">🔍 Inspeccionar contexto</button>
        <button type="button" class="btn btn-secondary btn-sm" data-project-action="discover" data-project-id="${escapeHtml(projectId(project))}">🔄 Explorar</button>
        <button type="button" class="btn btn-primary btn-sm" data-project-action="backlog" data-project-id="${escapeHtml(projectId(project))}">📥 Abrir trabajo</button>
      </div>
    </div>
  `).join("");
}
