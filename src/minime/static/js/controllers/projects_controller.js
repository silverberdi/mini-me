/** Owns project discovery, onboarding, and context inspection workflows. */
export function createProjectsController({
  fetchRequest,
  notify,
  onUnauthorized,
  getCurrentProjectId,
  setCurrentProjectId,
  getCurrentView,
  renderProjectSelect,
  renderProjectsGrid,
  projectSelect,
  backlogProjectDisplay,
  projectGrid,
  onboardingButton,
  onboardingModal,
  onboardingForm,
  cancelOnboardingButton,
  contextModal,
  closeContextButton,
  contextNodes,
  discoverBacklog,
  openBacklog,
  fetchBacklog,
}) {
  let projects = [];
  let bound = false;
  let projectFetchSequence = 0;

  function renderContextReport(report) {
    const { discoveredFacts, inferredStructure, missingContext } = contextNodes;
    if (discoveredFacts) {
      discoveredFacts.innerHTML = !report.discovered_facts?.length
        ? '<p class="text-muted">No facts discovered.</p>'
        : report.discovered_facts.map((fact) => `
          <div class="fact-card"><div class="fact-header">
            <span class="badge badge-discovered">${escapeHtml(fact.fact_type)}</span>
            <span class="fact-source font-mono text-xs">${escapeHtml(fact.source_file)}</span>
          </div><div class="fact-content">${escapeHtml(fact.content)}</div></div>`).join('');
    }
    if (inferredStructure) {
      inferredStructure.innerHTML = !report.inferred_structure?.length
        ? '<li class="text-muted">No inferred milestones or waves.</li>'
        : report.inferred_structure.map((value) => `<li>${escapeHtml(value)}</li>`).join('');
    }
    if (missingContext) {
      missingContext.innerHTML = !report.missing_context?.length
        ? '<li class="text-success">✓ No critical context gaps identified.</li>'
        : report.missing_context.map((gap) => `<li class="text-warning">⚠️ ${escapeHtml(gap)}</li>`).join('');
    }
  }

  async function fetchProjects() {
    const requestSequence = ++projectFetchSequence;
    try {
      const response = await fetchRequest('/projects');
      if ([401, 403].includes(response.status)) {
        if (requestSequence === projectFetchSequence) onUnauthorized();
        return [];
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const result = await response.json();
      if (requestSequence !== projectFetchSequence) return [];
      projects = result;
      const currentId = renderProjectSelect(projectSelect, projects, projectSelect?.value || getCurrentProjectId());
      if (backlogProjectDisplay) backlogProjectDisplay.textContent = `Proyecto: ${currentId || 'DESCONOCIDO'}`;
      if (currentId !== getCurrentProjectId()) setCurrentProjectId(currentId);
      if (getCurrentView() === 'viewProjects') renderProjectsGrid(projectGrid, projects, currentId);
      return projects;
    } catch (error) {
      if (requestSequence !== projectFetchSequence) return [];
      console.error('Failed to fetch projects:', error);
      notify(`No se pudieron cargar los proyectos: ${error.message}`, 'error');
      return [];
    }
  }

  function clear() {
    projectFetchSequence += 1;
    projects = [];
    setCurrentProjectId(null);
    if (projectSelect) {
      projectSelect.replaceChildren();
      projectSelect.value = '';
    }
    if (backlogProjectDisplay) backlogProjectDisplay.textContent = 'Proyecto: DESCONOCIDO';
    if (projectGrid) projectGrid.replaceChildren();
    contextModal?.close();
    Object.values(contextNodes).forEach((node) => { if (node) node.replaceChildren(); });
  }

  async function submitOnboarding() {
    const value = (id) => document.getElementById(id)?.value.trim();
    const repository = value('onboardRepository');
    if (!repository) {
      notify('Repository is required', 'warning');
      return;
    }
    try {
      const response = await fetchRequest('/api/v1/projects/onboard', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: value('onboardProjectId') || undefined,
          name: value('onboardProjectName') || undefined,
          repository,
          base_branch: value('onboardBaseBranch') || 'main',
          openspec_path: value('onboardOpenSpecPath') || 'openspec',
          roadmap_path: value('onboardRoadmapPath') || 'docs/ROADMAP.md',
          backlog_path: value('onboardBacklogPath') || 'docs/ROADMAP.md',
        }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${response.status}`);
      }
      const result = await response.json();
      notify(`Project '${result.project.name}' onboarded successfully! Discovered ${result.discovered_items_count} backlog items.`, 'success');
      onboardingModal?.close();
      await fetchProjects();
      setCurrentProjectId(result.project.id);
      if (projectSelect) projectSelect.value = result.project.id;
      openBacklog();
    } catch (error) {
      console.error('Failed onboarding project:', error);
      notify(`Onboarding failed: ${error.message}`, 'error');
    }
  }

  async function inspectContext(projectId) {
    try {
      const response = await fetchRequest(`/api/v1/projects/${encodeURIComponent(projectId)}/context`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      renderContextReport(await response.json());
      contextModal?.showModal();
    } catch (error) {
      console.error('Failed fetching context:', error);
      notify(`Failed inspecting context: ${error.message}`, 'error');
    }
  }

  function bindEvents() {
    if (bound) return;
    bound = true;
    projectSelect?.addEventListener('change', (event) => {
      const projectId = event.target.value || null;
      setCurrentProjectId(projectId);
      if (backlogProjectDisplay) backlogProjectDisplay.textContent = `Proyecto: ${projectId || 'DESCONOCIDO'}`;
      if (getCurrentView() === 'viewBacklog') void fetchBacklog(projectId);
    });
    projectGrid?.addEventListener('click', (event) => {
      const button = event.target.closest('[data-project-action][data-project-id]');
      if (!button) return;
      const projectId = button.dataset.projectId;
      if (button.dataset.projectAction === 'inspect') void inspectContext(projectId);
      else if (button.dataset.projectAction === 'discover') void discoverBacklog(projectId);
      else if (button.dataset.projectAction === 'backlog') {
        setCurrentProjectId(projectId);
        if (projectSelect) projectSelect.value = projectId;
        openBacklog();
      }
    });
    onboardingButton?.addEventListener('click', () => {
      onboardingForm?.reset();
      onboardingModal?.showModal();
    });
    cancelOnboardingButton?.addEventListener('click', () => onboardingModal?.close());
    onboardingForm?.addEventListener('submit', (event) => {
      event.preventDefault();
      void submitOnboarding();
    });
    closeContextButton?.addEventListener('click', () => contextModal?.close());
  }

  return { fetchProjects, inspectContext, bindEvents, clear, get projects() { return projects; } };
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[character]);
}
