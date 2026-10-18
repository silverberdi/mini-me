import { api } from "./services/api_client.js";
import { setOfflineBanner } from "./components/offline_banner.js";
import { initDesktopPaneLayout } from "./desktop_pane_layout.js";
import { openConfirmModal, openParamModal } from "./components/action_dialog.js";
import { createThemeController } from "./components/theme_controller.js";
import { createSessionController } from "./services/session_controller.js";
import { renderOperationalPanels as renderOperationalPanelsView, updateSchedulerServiceObservation } from "./views/operational_panels_view.js";
import { renderOverviewView } from "./views/overview_view.js";
import { renderProjectSelect as renderProjectSelectView, renderProjectsGrid as renderProjectsGridView } from "./views/projects_view.js";
import { renderPipelineStepper as renderPipelineStepperView } from "./components/pipeline_stepper.js";
import { renderBacklogDetail as renderBacklogDetailView, renderBacklogTable as renderBacklogTableView } from "./views/backlog_view.js";
import { renderAuditEvidence, renderCandidateEvidence, renderChecksEvidence, renderReviewEvidence, renderRunOverview } from "./views/evidence_views.js";
import { actionHistory, discoverActions, executeAction } from "./services/control_plane_client.js";
import { renderChangesView } from "./views/runs_view.js";
import { createActionController } from "./controllers/action_controller.js";
import { createPreviewController } from "./controllers/preview_controller.js";
import { createBacklogController } from "./controllers/backlog_controller.js";
import { createLifecycleController } from "./controllers/lifecycle_controller.js";
import { createProjectsController } from "./controllers/projects_controller.js";
import { createNavigationController } from "./controllers/navigation_controller.js";
import { getStatusBadgeClass } from "./views/status_view.js";

/** Single native-module coordinator for the existing Control Center workflows. */
// Operational and authenticated responses must never be read from the HTTP cache.
const fetch = (input, init = {}) => {
  const method = String(init.method || "GET").toUpperCase();
  if (method !== "GET" && navigator.onLine === false) {
    return Promise.reject(Object.assign(new Error("Sin conexión; no se envió la acción."), { status: 503 }));
  }
  return window.fetch(input, { ...init, cache: "no-store", credentials: "same-origin" });
};

  // Safe Storage Helpers
  // State
  let overviewData = null;
  let queueData = null;
  let providerData = null;
  let healthData = null;
  let selectedChange = null;
  let detailRequestSequence = 0;
  let refreshInProgress = false;
  let refreshPending = false;
  let initialSelected = false;
  let navigationController = null;

  // 021 Intake & Projects State
  let currentProjectId = null;
  let backlogItems = [];
  let selectedBacklogItem = null;
  let editingItemKey = null;

  // DOM Elements
  const appVersionBadge = document.getElementById('appVersionBadge');
  const schedulerModeBadge = document.getElementById('schedulerModeBadge');
  const dbHealthBadge = document.getElementById('dbHealthBadge');
  const refreshBtn = document.getElementById('refreshBtn');
  const themeController = createThemeController(
    document.getElementById('themeToggleBtn'),
    document.getElementById('themeIcon'),
  );
  const autoRefreshToggle = document.getElementById('autoRefreshToggle');
  const refreshIntervalSelect = document.getElementById('refreshIntervalSelect');
  const refreshTimer = document.getElementById('refreshTimer');

  // Main Nav Tabs & Views
  const mainNavTabs = document.querySelectorAll('.main-tab-btn');
  const mainViewPanes = document.querySelectorAll('.main-view-pane');
  const projectSelect = document.getElementById('projectSelect');

  // Backlog DOM Elements
  const backlogProjectDisplay = document.getElementById('backlogProjectDisplay');
  const backlogSearchInput = document.getElementById('backlogSearchInput');
  const backlogStatusPills = document.querySelectorAll('#backlogStatusPills .pill');
  const newWorkItemBtn = document.getElementById('newWorkItemBtn');
  const discoverBacklogBtn = document.getElementById('discoverBacklogBtn');
  const backlogTableBody = document.getElementById('backlogTableBody');
  const backlogPlaceholder = document.getElementById('backlogPlaceholder');
  const backlogDetailContent = document.getElementById('backlogDetailContent');
  const bkTitle = document.getElementById('bkTitle');
  const bkStatusBadge = document.getElementById('bkStatusBadge');
  const bkPriorityBadge = document.getElementById('bkPriorityBadge');
  const bkKey = document.getElementById('bkKey');
  const bkSource = document.getElementById('bkSource');
  const bkReadiness = document.getElementById('bkReadiness');
  const bkPrepareBtn = document.getElementById('bkPrepareBtn');
  const bkStartBtn = document.getElementById('bkStartBtn');
  const bkEditBtn = document.getElementById('bkEditBtn');
  const bkDeleteBtn = document.getElementById('bkDeleteBtn');
  const bkNeedsHumanCard = document.getElementById('bkNeedsHumanCard');
  const bkHumanQuestionsList = document.getElementById('bkHumanQuestionsList');
  const answerQuestionForm = document.getElementById('answerQuestionForm');
  const answerQuestionTarget = document.getElementById('answerQuestionTarget');
  const humanAnswerInput = document.getElementById('humanAnswerInput');
  const bkDescriptionPreview = document.getElementById('bkDescriptionPreview');
  const bkCriteriaList = document.getElementById('bkCriteriaList');
  const bkDorOverallPill = document.getElementById('bkDorOverallPill');
  const bkDorGrid = document.getElementById('bkDorGrid');
  const bkArtOpenSpec = document.getElementById('bkArtOpenSpec');
  const bkArtIssue = document.getElementById('bkArtIssue');
  const bkArtProject = document.getElementById('bkArtProject');
  const bkArtRun = document.getElementById('bkArtRun');

  // Projects DOM Elements
  const projectsGridContainer = document.getElementById('projectsGridContainer');
  const onboardProjectBtn = document.getElementById('onboardProjectBtn');
  const onboardProjectModal = document.getElementById('onboardProjectModal');
  const onboardProjectForm = document.getElementById('onboardProjectForm');
  const cancelOnboardBtn = document.getElementById('cancelOnboardBtn');
  const projectContextModal = document.getElementById('projectContextModal');
  const closeContextModalBtn = document.getElementById('closeContextModalBtn');
  const ctxDiscoveredFacts = document.getElementById('ctxDiscoveredFacts');
  const ctxInferredStructure = document.getElementById('ctxInferredStructure');
  const ctxMissingContext = document.getElementById('ctxMissingContext');

  // Work Item Modal Elements
  const newWorkItemModal = document.getElementById('newWorkItemModal');
  const newWorkItemForm = document.getElementById('newWorkItemForm');
  const workItemModalTitle = document.getElementById('workItemModalTitle');
  const newWorkItemTitle = document.getElementById('newWorkItemTitle');
  const newWorkItemKey = document.getElementById('newWorkItemKey');
  const newWorkItemPriority = document.getElementById('newWorkItemPriority');
  const newWorkItemDescription = document.getElementById('newWorkItemDescription');
  const newWorkItemCriteria = document.getElementById('newWorkItemCriteria');
  const cancelWorkItemBtn = document.getElementById('cancelWorkItemBtn');

  const kpiSystemStateVal = document.getElementById('kpiSystemStateVal');
  const kpiSystemStateSub = document.getElementById('kpiSystemStateSub');
  const kpiAttentionVal = document.getElementById('kpiAttentionVal');
  const kpiAttentionSub = document.getElementById('kpiAttentionSub');
  const kpiActiveVal = document.getElementById('kpiActiveVal');
  const kpiActiveSub = document.getElementById('kpiActiveSub');
  const kpiCompletedVal = document.getElementById('kpiCompletedVal');
  const kpiCompletedSub = document.getElementById('kpiCompletedSub');

  const attentionBanner = document.getElementById('attentionBanner');
  const attentionCountText = document.getElementById('attentionCountText');
  const attentionItemsContainer = document.getElementById('attentionItemsContainer');

  const changeSearchInput = document.getElementById('changeSearchInput');
  const filterPills = document.querySelectorAll('.filter-pills .pill');
  const changesTableBody = document.getElementById('changesTableBody');

  const detailPlaceholder = document.getElementById('detailPlaceholder');
  const detailContent = document.getElementById('detailContent');
  const dtChangeName = document.getElementById('dtChangeName');
  const dtStatusBadge = document.getElementById('dtStatusBadge');
  const dtProject = document.getElementById('dtProject');
  const dtRepository = document.getElementById('dtRepository');
  const dtStage = document.getElementById('dtStage');
  const dtGeneration = document.getElementById('dtGeneration');
  const dtCandidateSha = document.getElementById('dtCandidateSha');
  const copyShaBtn = document.getElementById('copyShaBtn');

  const pipelineStepper = document.getElementById('pipelineStepper');
  const detailTabs = document.querySelectorAll('.detail-tabs .tab-btn');
  const tabPanes = document.querySelectorAll('.tab-pane');

  // Auth DOM Elements
  const loginSection = document.getElementById('loginSection');
  const authenticatedContent = document.getElementById('authenticatedContent');
  const operatorProfileGroup = document.getElementById('operatorProfileGroup');
  const operatorEmailText = document.getElementById('operatorEmailText');
  const logoutBtn = document.getElementById('logoutBtn');
  const lifecycleController = createLifecycleController({
    refreshCurrentView: () => {
      if (navigationController?.currentView === 'viewBacklog') return fetchBacklog(currentProjectId);
      if (navigationController?.currentView === 'viewProjects') return fetchProjects();
      return fetchOverview();
    },
    refreshAfterReconnect: () => {
      if (navigationController?.currentView === 'viewBacklog') void fetchBacklog(currentProjectId);
      else if (navigationController?.currentView === 'viewProjects') void fetchProjects();
      return fetchOverview();
    },
    refreshOverview: fetchOverview,
    setOfflineBanner,
    markFreshnessStale: () => {
      ["overviewFreshness", "queueFreshness", "providerFreshness", "healthFreshness"].forEach((id) => {
        const node = document.getElementById(id);
        if (node) {
          node.textContent = "Sin conexión: la última lectura puede estar desactualizada.";
          node.dataset.state = "STALE";
        }
      });
    },
    onResize: () => {
      const executions = document.getElementById('viewExecutions');
      if (executions?.classList.contains('active')) {
        executions.style.display = window.matchMedia('(min-width: 1200px)').matches ? 'grid' : 'block';
      }
    },
    refreshButton: refreshBtn,
    refreshIntervalSelect,
    autoRefreshToggle,
    refreshTimer,
  });
  const sessionController = createSessionController({
    fetch,
    loginSection,
    authenticatedContent,
    profileGroup: operatorProfileGroup,
    emailNode: operatorEmailText,
    onAuthenticated: (operator) => { void initDesktopPaneLayout(operator.email); },
    onUnauthenticated: () => {
      lifecycleController.stop();
      overviewData = null;
      queueData = null;
      providerData = null;
      healthData = null;
      selectedChange = null;
      renderOverview();
      renderOperationalPanels({
        overviewResult: { status: "rejected" },
        queueResult: { status: "rejected" },
        providerResult: { status: "rejected" },
        healthResult: { status: "rejected" },
      });
      setOfflineBanner(false);
    },
  });
  const actionController = createActionController({
    execute: executeAction,
    discover: discoverActions,
    notify: showToast,
    refreshOverview: fetchOverview,
    refreshSelectedDetail: async () => {
      if (selectedChange?.project_id && selectedChange?.change_name) {
        await fetchChangeDetail(selectedChange.project_id, selectedChange.change_name);
      }
    },
    getActor: () => sessionController.currentUser?.email,
    toolbar: document.getElementById('actionToolbar'),
    escapeHtml,
    openParameters: openParamModal,
    openConfirmation: openConfirmModal,
  });
  const previewController = createPreviewController({
    fetchRequest: fetch,
    notify: showToast,
    refresh: fetchOverview,
    getActor: () => sessionController.currentUser?.email,
  });
  const backlogController = createBacklogController({
    fetchRequest: fetch,
    notify: showToast,
    getProjectId: () => currentProjectId,
    refreshBacklog: fetchBacklog,
    refreshProjects: fetchProjects,
    selectItem: selectBacklogItem,
    clearSelectedItem: () => { selectedBacklogItem = null; },
    onStarted: () => setTimeout(() => switchMainView('viewExecutions'), 1000),
    confirmAction: (message) => window.confirm(message),
  });
  const projectsController = createProjectsController({
    fetchRequest: fetch,
    notify: showToast,
    onUnauthorized: () => sessionController.showLogin(),
    getCurrentProjectId: () => currentProjectId,
    setCurrentProjectId: (projectId) => { currentProjectId = projectId; },
    getCurrentView: () => navigationController?.currentView,
    renderProjectSelect: renderProjectSelectView,
    renderProjectsGrid: renderProjectsGridView,
    projectSelect,
    backlogProjectDisplay,
    projectGrid: projectsGridContainer,
    onboardingButton: onboardProjectBtn,
    onboardingModal: onboardProjectModal,
    onboardingForm: onboardProjectForm,
    cancelOnboardingButton: cancelOnboardBtn,
    contextModal: projectContextModal,
    closeContextButton: closeContextModalBtn,
    contextNodes: {
      discoveredFacts: ctxDiscoveredFacts,
      inferredStructure: ctxInferredStructure,
      missingContext: ctxMissingContext,
    },
    discoverBacklog: (projectId) => backlogController.discover(projectId),
    openBacklog: () => switchMainView('viewBacklog'),
    fetchBacklog,
  });
  navigationController = createNavigationController({
    documentRef: document,
    windowRef: window,
    mainNavTabs,
    bottomNavTabs: document.querySelectorAll('.bottom-nav [data-main-view]'),
    scrollButtons: document.querySelectorAll('.bottom-nav [data-scroll-to]'),
    mainViewPanes,
    detailTabs,
    tabPanes,
    changeSearchInput,
    filterPills,
    changesTableBody,
    attentionItemsContainer,
    copyShaButton: copyShaBtn,
    candidateShaNode: dtCandidateSha,
    fetchBacklog: () => currentProjectId ? fetchBacklog(currentProjectId) : renderBacklogUnavailable(),
    fetchProjects,
    fetchOverview,
    renderBacklogUnavailable,
    renderChangesTable,
    selectChange,
  });

  // Initialization
  export async function initDashboard() {
    themeController.initialize();
    sessionController.bindLogout(logoutBtn);
    lifecycleController.bind();
    projectsController.bindEvents();
    navigationController.bind();
    actionController.bindToolbar();
    backlogController.bindEvents({
      searchInput: backlogSearchInput,
      statusPills: backlogStatusPills,
      tableBody: backlogTableBody,
      newItemButton: newWorkItemBtn,
      cancelButton: cancelWorkItemBtn,
      itemModal: newWorkItemModal,
      itemForm: newWorkItemForm,
      discoverButton: discoverBacklogBtn,
      prepareButton: bkPrepareBtn,
      startButton: bkStartBtn,
      editButton: bkEditBtn,
      deleteButton: bkDeleteBtn,
      answerForm: answerQuestionForm,
      answerInput: humanAnswerInput,
      runArtifact: bkArtRun,
      getSelectedItem: () => selectedBacklogItem,
      openEditor: (item) => openNewWorkItemModal(item),
      saveForm: saveWorkItem,
      renderTable: renderBacklogTable,
      clearAnswer: () => { if (humanAnswerInput) humanAnswerInput.value = ''; },
      onOpenRun: () => switchMainView('viewExecutions'),
    });
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => {});
    }
    const authenticated = await sessionController.checkAuth();
    if (authenticated) {
      await fetchProjects();
      switchMainView('viewExecutions');
      lifecycleController.start();
    }
  }

  // API Fetching
  async function fetchOverview() {
    if (refreshInProgress) {
      refreshPending = true;
      return;
    }
    refreshInProgress = true;
    try {
      do {
        refreshPending = false;
        await fetchOverviewOnce();
      } while (refreshPending);
    } finally {
      refreshInProgress = false;
    }
  }

  async function fetchOverviewOnce() {
    const [overviewResult, queueResult, providerResult, healthResult] = await Promise.allSettled([
      api.overview(), api.queue(), api.providers(), api.health(),
    ]);
    const unauthorized = [overviewResult, queueResult, providerResult, healthResult]
      .some((result) => result.status === "rejected" && [401, 403].includes(result.reason?.status));
    if (unauthorized) {
      overviewData = null;
      queueData = null;
      providerData = null;
      healthData = null;
      sessionController.showLogin();
      renderOverview();
      renderOperationalPanels({ overviewResult, queueResult, providerResult, healthResult });
      return;
    }
    if (overviewResult.status === "rejected") {
      if ([401, 403].includes(overviewResult.reason?.status)) sessionController.showLogin();
      overviewData = null;
    } else {
      overviewData = overviewResult.value;
    }
    queueData = queueResult.status === "fulfilled" ? queueResult.value : null;
    providerData = providerResult.status === "fulfilled" ? providerResult.value : null;
    healthData = healthResult.status === "fulfilled" ? healthResult.value : null;
    renderOverview();
    renderOperationalPanels({ overviewResult, queueResult, providerResult, healthResult });
    if (selectedChange && overviewData) {
      fetchChangeDetail(selectedChange.project_id, selectedChange.change_name);
    }
  }

  function renderOperationalPanels(results) {
    renderOperationalPanelsView({
      data: { overview: overviewData, queue: queueData, providers: providerData, health: healthData },
      results: {
        overview: results.overviewResult,
        queue: results.queueResult,
        providers: results.providerResult,
        health: results.healthResult,
      },
      elements: {
        queueList: document.getElementById("queueList"),
        providerGrid: document.getElementById("providerGrid"),
        overviewFreshness: document.getElementById("overviewFreshness"),
        queueFreshness: document.getElementById("queueFreshness"),
        providerFreshness: document.getElementById("providerFreshness"),
        healthFreshness: document.getElementById("healthFreshness"),
        dbHealthBadge,
        kpiSystemStateVal,
      },
      selectChange,
      formatRelativeTime,
    });
  }

  async function fetchChangeDetail(projectId, changeName) {
    const requestSequence = ++detailRequestSequence;
    try {
      const resp = await fetch(`/api/v1/dashboard/changes/${encodeURIComponent(projectId)}/${encodeURIComponent(changeName)}`);
      if ([401, 403].includes(resp.status)) {
        sessionController.showLogin();
        return;
      }
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const detailData = await resp.json();
      if (requestSequence !== detailRequestSequence
          || selectedChange?.project_id !== projectId
          || selectedChange?.change_name !== changeName) return;
      if (detailData.project_id !== projectId || detailData.change_name !== changeName) {
        throw new Error('La respuesta no coincide con la identidad del cambio seleccionado.');
      }
      renderDetail(detailData);
    } catch (err) {
      if (requestSequence === detailRequestSequence) {
        console.error('No se pudo consultar el detalle del cambio:', err);
        if (detailContent) detailContent.style.display = 'none';
        if (detailPlaceholder) {
          detailPlaceholder.style.display = 'block';
          detailPlaceholder.textContent = 'Detalle no disponible; vuelve a actualizar cuando se recupere la conexión.';
        }
      }
    }
  }

  // Rendering
  function renderOverview() {
    if (!overviewData) {
      setOfflineBanner(typeof navigator !== "undefined" && navigator.onLine === false);
    } else {
      setOfflineBanner(false);
    }
    renderOverviewView({
      data: overviewData,
      elements: {
        kpiGrid: document.getElementById("operationalKpis"),
        schedulerServiceBadge: document.getElementById("schedulerServiceBadge"),
        schedulerModeBadge,
        kpiSystemStateVal,
        kpiSystemStateSub,
        kpiAttentionVal,
        kpiAttentionSub,
        kpiActiveVal,
        kpiActiveSub,
        kpiCompletedVal,
        kpiCompletedSub,
        attentionBanner,
        attentionCountText,
        attentionItemsContainer,
        changesTableBody,
        detailContent,
        detailPlaceholder,
      },
      escapeHtml,
      updateSchedulerServiceObservation,
      renderChanges: renderChangesTable,
    });
  }

  function renderChangesTable() {
    if (!overviewData || !overviewData.changes) return;
    initialSelected = renderChangesView({
      root: changesTableBody,
      changes: overviewData.changes,
      filter: navigationController.activeFilter,
      query: navigationController.searchQuery,
      selected: selectedChange,
      alreadyAutoSelected: initialSelected,
      statusClass: getStatusBadgeClass,
      formatTime: formatRelativeTime,
      onSelect: selectChange,
    });
  }

  function selectChange(projectId, changeName) {
    selectedChange = { project_id: projectId, change_name: changeName };
    if (detailContent) detailContent.style.display = 'none';
    if (detailPlaceholder) {
      detailPlaceholder.style.display = 'block';
      detailPlaceholder.textContent = 'Cargando evidencia del cambio seleccionado…';
    }
    renderChangesTable();
    fetchChangeDetail(projectId, changeName);
  }

  function renderDetail(detail) {
    if (!detail) return;

    detailPlaceholder.style.display = 'none';
    detailContent.style.display = 'block';

    // Header
    dtChangeName.textContent = detail.change_name;
    dtStatusBadge.textContent = detail.status;
    dtStatusBadge.className = `badge ${getStatusBadgeClass(detail.status)}`;
    dtProject.textContent = detail.project_id;
    const bindingState = detail.repository_binding_state || 'UNKNOWN';
    dtRepository.textContent = bindingState === 'VALID'
      ? (detail.repository_identity || 'UNKNOWN')
      : bindingState === 'INVALID' ? 'Vínculo inválido' : 'UNKNOWN';
    dtRepository.dataset.state = bindingState;
    dtStage.textContent = detail.current_stage || '---';

    const gen = detail.candidate_authority ? `gen-${detail.candidate_authority.generation}` : '---';
    dtGeneration.textContent = gen;

    if (detail.candidate_authority && detail.candidate_authority.candidate_sha) {
      dtCandidateSha.textContent = detail.candidate_authority.candidate_sha_short;
      dtCandidateSha.setAttribute('data-full-sha', detail.candidate_authority.candidate_sha);
      copyShaBtn.style.display = 'inline-block';
    } else {
      dtCandidateSha.textContent = '---';
      copyShaBtn.style.display = 'none';
    }

    // 6-Phase Pipeline Stepper
    renderPipelineStepper(detail.pipeline);

    // Tab 1: Overview & Attention
    renderOverviewTab(detail);

    // Tab 2: Candidate Authority
    renderCandidateTab(detail);

    // Tab 3: Checks
    renderChecksTab(detail.checks);

    // Tab 4: Review
    renderReviewTab(detail.review, detail.candidate_authority);

    // Tab 5: Audit
    renderAuditTab(detail.audit, detail.candidate_authority);

    // Tab 6: Container Preview & Guided Validation
    renderPreviewTab(detail.preview_validation, detail);

    // Tab 7: GitHub & PR
    renderGitHubTab(detail.github, detail.project_id);

    // Tab 8: Provider Efficiency & Telemetry
    renderEfficiencyTab(detail.project_id, detail.change_name);

    // Tab 9: Action History Audit Trail
    renderActionHistoryTab(detail.run_id);

    // Tab 10: Timeline
    renderTimelineTab(detail.timeline);

    // Action Toolbar
    void actionController.renderToolbar(detail);
  }

  function showToast(message, type = 'info') {
    const toast = document.getElementById('toastNotification');
    if (!toast) return;
    toast.textContent = message;
    toast.className = `toast-notification toast-${type}`;
    toast.style.display = 'block';
    setTimeout(() => {
      toast.style.display = 'none';
    }, 4000);
  }

  async function renderEfficiencyTab(projectId, changeName) {
    const container = document.getElementById('efficiencyDetailsContainer');
    if (!container) return;
    if (!projectId || !changeName) {
      container.innerHTML = '<p class="table-empty">No hay telemetría registrada para este cambio.</p>';
      return;
    }
    try {
      const resp = await fetch(`/api/v1/efficiency/${encodeURIComponent(projectId)}/${encodeURIComponent(changeName)}`);
      if (!resp.ok) {
        container.innerHTML = '<p class="table-empty">No hay telemetría de eficiencia de proveedores para este cambio.</p>';
        return;
      }
      const data = await resp.json();
      const metrics = data.metrics || data;
      const ratio = data.productive_attempt_ratio !== undefined
        ? `${(Number(data.productive_attempt_ratio) * 100).toFixed(0)}%` : 'No informado';
      const attempts = data.total_attempts ?? 'No informado';
      const reworks = metrics.corrective_retry_count ?? data.rework_attempts ?? 'No informado';
      const model = data.primary_model || data.provider_summary?.[0]?.provider || 'No informado';
      const reviewerModel = data.reviewer_model || data.provider_summary?.[1]?.provider || 'No informado';
      const indStatus = data.reviewer_independence === true ? 'VERIFICADA'
        : data.reviewer_independence === false ? 'NO VERIFICADA' : 'DESCONOCIDA';
      const selfHost = metrics.self_hosting_percentage !== undefined
        ? `${metrics.self_hosting_percentage.toFixed(0)}%` : 'No informado';

      container.innerHTML = `
        <div class="efficiency-kpi-grid">
          <div class="stat-card">
            <div class="stat-label">INTENTOS PRODUCTIVOS</div>
            <div class="stat-value text-success">${escapeHtml(ratio)}</div>
            <div class="stat-sub">${attempts} intentos en total (${reworks} reintentos correctivos)</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">IMPLEMENTADOR PRINCIPAL</div>
            <div class="stat-value">${escapeHtml(model)}</div>
            <div class="stat-sub">Proveedor de implementación</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">REVISOR COMPLEMENTARIO</div>
            <div class="stat-value">${escapeHtml(reviewerModel)}</div>
            <div class="stat-sub">Independencia: <strong class="text-success">${escapeHtml(indStatus)}</strong></div>
          </div>
          <div class="stat-card">
            <div class="stat-label">EJECUCIÓN NATIVA</div>
            <div class="stat-value text-primary">${escapeHtml(selfHost)}</div>
            <div class="stat-sub">Telemetry verified</div>
          </div>
        </div>
        <div class="section-card" style="margin-top: 16px;">
          <h5 class="section-subtitle">Anti-Loop & Retry Telemetry</h5>
          <div class="overview-meta-grid" style="margin-top: 8px;">
            <div class="meta-item"><span class="meta-label">Same-SHA Retries</span><span class="meta-val">${escapeHtml(metrics.same_sha_retry_count || 0)}</span></div>
            <div class="meta-item"><span class="meta-label">Same-SHA Suppressed</span><span class="meta-val">${escapeHtml(metrics.same_sha_retry_suppressed_count || 0)}</span></div>
            <div class="meta-item"><span class="meta-label">Candidate Generations</span><span class="meta-val">${escapeHtml(metrics.candidate_generations_count || 1)}</span></div>
            <div class="meta-item"><span class="meta-label">Reassignments</span><span class="meta-val">${escapeHtml(metrics.reassignments_count || 0)}</span></div>
            <div class="meta-item"><span class="meta-label">Evaluated At</span><span class="meta-val">${formatTimestamp(data.evaluated_at || metrics.updated_at)}</span></div>
          </div>
        </div>
      `;
    } catch (err) {
      container.innerHTML = '<p class="table-empty">No se pudo cargar la telemetría de eficiencia.</p>';
    }
  }

  async function renderActionHistoryTab(runId) {
    const container = document.getElementById('actionHistoryContentContainer');
    if (!container) return;
    if (!runId) {
      container.innerHTML = '<p class="table-empty">No hay historial de acciones para esta ejecución.</p>';
      return;
    }
    try {
      const history = await actionHistory(runId);
      if (!history || !history.length) {
        container.innerHTML = '<p class="table-empty">Aún no hay acciones del operador registradas para este Run.</p>';
        return;
      }
      container.innerHTML = `
        <table class="data-table small-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Action</th>
              <th>Actor</th>
              <th>Status</th>
              <th>Source</th>
              <th>Summary / Reason</th>
            </tr>
          </thead>
          <tbody>
            ${history.map(item => {
              const statusClass = item.status === 'SUCCESS' ? 'badge-success' : (item.status === 'REJECTED' ? 'badge-warning' : 'badge-danger');
              return `
                <tr>
                  <td>${formatTimestamp(item.created_at || item.requested_at)}</td>
                  <td><span class="badge">${escapeHtml(item.action_type)}</span></td>
                  <td><strong>${escapeHtml(item.actor_identity || 'operator')}</strong></td>
                  <td><span class="badge ${statusClass}">${escapeHtml(item.status)}</span></td>
                  <td><code>${escapeHtml(item.source_interface || 'pwa')}</code></td>
                  <td>${escapeHtml(item.message || item.rejection_reason || item.details?.reason || 'Executed')}</td>
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>
      `;
    } catch (err) {
      container.innerHTML = '<p class="table-empty">No se pudo cargar la trazabilidad de acciones.</p>';
    }
  }


  function renderPipelineStepper(pipeline) {
    renderPipelineStepperView(pipelineStepper, pipeline);
  }

  function renderOverviewTab(detail) {
    renderRunOverview({
      metaGrid: document.getElementById('overviewMetaGrid'),
      blockerSection: document.getElementById('overviewBlockerSection'),
      blockersList: document.getElementById('overviewBlockersList'),
      detail,
    });
  }

  function renderCandidateTab(detail) {
    renderCandidateEvidence({
      summary: document.getElementById('candidateDetailsContainer'),
      history: document.getElementById('candidateHistoryBody'),
      detail,
    });
  }

  function renderChecksTab(checks) {
    renderChecksEvidence({
      count: document.getElementById('checksTabCount'),
      container: document.getElementById('checksListContainer'),
      checks,
    });
  }

  function renderReviewTab(review, candidate) {
    renderReviewEvidence({ container: document.getElementById('reviewDetailsContainer'), review, candidate });
  }

  function renderAuditTab(audit, candidate) {
    renderAuditEvidence({ container: document.getElementById('auditDetailsContainer'), audit, candidate });
  }

  function renderPreviewTab(previewVal, detail) {
    const statusContainer = document.getElementById('previewContainerStatus');
    const scenariosContainer = document.getElementById('guidedValidationContainer');
    const historyContainer = document.getElementById('validationHistoryContainer');
    const launchBtn = document.getElementById('launchPreviewBtn');
    const teardownBtn = document.getElementById('teardownPreviewBtn');

    if (!statusContainer || !scenariosContainer || !historyContainer) return;

    const session = previewVal ? previewVal.preview_session : null;
    const isRequired = previewVal ? previewVal.is_preview_required : false;
    const isAuthorized = previewVal ? previewVal.is_authorized : false;
    const isStale = previewVal ? previewVal.is_stale : false;
    const candSha = detail.candidate_authority?.candidate_sha || null;
    const baseSha = detail.candidate_authority?.base_sha || null;
    const candidateGeneration = detail.candidate_authority?.generation;
    const previewIdentityValid = Boolean(
      candSha && baseSha && Number.isInteger(candidateGeneration) && candidateGeneration > 0,
    );
    const previewMatchesCandidate = Boolean(session && previewIdentityValid
      && session.head_sha === candSha
      && session.base_sha === baseSha
      && Number(session.candidate_generation) === candidateGeneration
      && session.image_digest);
    const validationAllowed = previewMatchesCandidate && session.status === 'READY' && !isStale;

    // Action buttons visibility
    if (session && (session.status === 'READY' || session.status === 'STARTING' || session.status === 'PROBING')) {
      if (launchBtn) launchBtn.style.display = 'none';
      if (teardownBtn) {
        teardownBtn.style.display = 'inline-block';
        teardownBtn.onclick = () => previewController.teardown({ session, button: teardownBtn });
      }
    } else {
      if (teardownBtn) teardownBtn.style.display = 'none';
      if (launchBtn) {
        launchBtn.style.display = 'inline-block';
        launchBtn.disabled = !previewIdentityValid;
        launchBtn.title = previewIdentityValid
          ? 'Crear vista previa para la identidad exacta del candidato'
          : 'No disponible: falta identidad verificable de candidato, base o generación';
        launchBtn.onclick = () => previewController.launch({
          detail,
          candidate: { head_sha: candSha, base_sha: baseSha, generation: candidateGeneration },
          button: launchBtn,
        });
      }
    }

    // Render Preview Container Status Card
    if (!session) {
      statusContainer.innerHTML = `
        <div class="overview-meta-grid" style="margin-bottom: 8px;">
          <div class="meta-box">
          <div class="meta-box-label">Requisito de vista previa</div>
          <div class="meta-box-val">${isRequired ? '<span class="badge badge-warning">REQUERIDA PARA INTEGRAR</span>' : '<span class="text-muted">Opcional</span>'}</div>
          </div>
          <div class="meta-box">
          <div class="meta-box-label">Estado</div>
          <div class="meta-box-val"><span class="badge badge-discovered">NO INICIADA</span></div>
          </div>
          <div class="meta-box">
          <div class="meta-box-label">Veredicto de validación</div>
          <div class="meta-box-val"><span class="badge badge-not-ready">PENDIENTE</span></div>
          </div>
        </div>
      <p class="text-muted" style="font-size: 12px; margin: 0;">Inicia una vista previa aislada para el candidato seleccionado.</p>
      `;
    } else {
      const isReady = session.status === 'READY';
      const statusBadgeClass = isReady ? 'badge-ready' : (session.status === 'FAILED' ? 'badge-failed' : 'badge-running');
      statusContainer.innerHTML = `
        <div class="overview-meta-grid" style="margin-bottom: 12px;">
          <div class="meta-box">
          <div class="meta-box-label">Estado de la vista previa</div>
            <div class="meta-box-val"><span class="badge ${statusBadgeClass}">${escapeHtml(session.status)}</span></div>
          </div>
          <div class="meta-box">
          <div class="meta-box-label">URL de la vista previa</div>
            <div class="meta-box-val">
              ${session.preview_url ? `<a href="${sanitizeUrl(session.preview_url)}" target="_blank" rel="noopener noreferrer" class="text-primary font-mono font-bold">${escapeHtml(session.preview_url)} ↗</a>` : '<span class="text-muted">---</span>'}
            </div>
          </div>
          <div class="meta-box">
          <div class="meta-box-label">Puerto asignado</div>
            <div class="meta-box-val font-mono">${session.allocated_port || '---'}</div>
          </div>
          <div class="meta-box">
          <div class="meta-box-label">Autoridad de validación</div>
            <div class="meta-box-val">
              ${isAuthorized ? '<span class="badge badge-completed">APROBACIÓN REGISTRADA</span>' : (isStale ? '<span class="badge badge-warning">OBSOLETA (REQUIERE REVALIDACIÓN)</span>' : '<span class="badge badge-not-ready">REQUIERE VALIDACIÓN</span>')}
            </div>
          </div>
        </div>
        <div class="meta-box" style="margin-bottom: 8px;">
          <div class="meta-box-label">Digest inmutable de imagen</div>
          <div class="meta-box-val font-mono" style="font-size: 11px; word-break: break-all;">${escapeHtml(session.image_digest || '---')}</div>
        </div>
        ${session.failure_reason ? `
          <div class="meta-box" style="border-left: 3px solid var(--color-danger); margin-top: 8px;">
            <div class="meta-box-label text-danger">Failure Diagnostics (${escapeHtml(session.failure_code || 'ERROR')})</div>
            <p style="font-size: 11px; color: var(--color-danger); margin-top: 4px;">${escapeHtml(session.failure_reason)}</p>
          </div>
        ` : ''}
      `;
    }

    // Render Guided Validation Scenarios
    const scenarios = (previewVal && previewVal.scenarios) ? previewVal.scenarios : [];
    if (scenarios.length === 0) {
      scenariosContainer.innerHTML = `<p class="text-muted" style="font-size: 12px;">No hay escenarios de validación definidos para este cambio.</p>`;
    } else {
      scenariosContainer.innerHTML = `
        <div class="checks-list" style="margin-bottom: 16px;">
          ${scenarios.map((sc, scIdx) => `
            <div class="check-item" style="flex-direction: column; align-items: flex-start; gap: 6px;">
              <div style="display: flex; justify-content: space-between; width: 100%; align-items: center;">
                <div class="check-item-title font-bold">${escapeHtml(sc.title)}</div>
                <span class="badge ${sc.required ? 'badge-ready' : 'badge-discovered'}">${sc.required ? 'Obligatorio' : 'Opcional'}</span>
              </div>
              <p style="font-size: 12px; margin: 0; color: var(--text-muted);">${escapeHtml(sc.description)}</p>
              ${sc.ordered_steps && sc.ordered_steps.length > 0 ? `
                <div style="margin-top: 4px; padding-left: 8px; font-size: 11px;">
                  ${sc.ordered_steps.map((st, stIdx) => `
                    <label style="display: flex; align-items: center; gap: 6px; margin: 3px 0; cursor: pointer;">
                      <input type="checkbox" class="scenario-step-check" data-scenario-id="${escapeHtml(sc.scenario_id)}" data-step-idx="${stIdx}">
                      <span>${escapeHtml(st)}</span>
                    </label>
                  `).join('')}
                </div>
              ` : `<label class="validation-scenario-completion"><input type="checkbox" class="scenario-complete-check" data-scenario-id="${escapeHtml(sc.scenario_id)}"><span>Confirmo que completé este escenario.</span></label>`}
            </div>
          `).join('')}
        </div>

        <div class="validation-submission-form" style="background: var(--bg-card-sub); padding: 12px; border-radius: 6px; border: 1px solid var(--border-color);">
          <h5 style="margin: 0 0 10px 0; font-size: 13px;">Registrar validación del candidato</h5>
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 10px;">
            <div>
              <label style="font-size: 11px; color: var(--text-muted); display: block; margin-bottom: 4px;">Veredicto</label>
              <select id="validationVerdictSelect" style="width: 100%; padding: 6px; border-radius: 4px; border: 1px solid var(--border-color); background: var(--bg-input); color: var(--text-primary);">
                <option value="PASS" selected>PASS — Validación visual completada</option>
                <option value="FAIL">FAIL — Se observaron defectos</option>
              </select>
            </div>
            <p class="text-muted" id="validationOperatorIdentity">La validación se registrará con la identidad autenticada.</p>
          </div>
          <div style="margin-bottom: 10px;">
            <label style="font-size: 11px; color: var(--text-muted); display: block; margin-bottom: 4px;">Notas u observaciones</label>
            <textarea id="validationNotesInput" rows="2" placeholder="Describe los flujos comprobados o los defectos observados…" style="width: 100%; padding: 6px; border-radius: 4px; border: 1px solid var(--border-color); background: var(--bg-input); color: var(--text-primary); font-size: 12px;"></textarea>
          </div>
          <button id="submitValidationBtn" class="btn btn-primary btn-sm" ${validationAllowed ? '' : 'disabled'}>Registrar validación</button>
          ${validationAllowed ? '' : '<p class="text-muted">No disponible: falta una vista previa READY vinculada a este candidato o la evidencia está obsoleta.</p>'}
        </div>
      `;

      // Wire submit button
      const submitBtn = document.getElementById('submitValidationBtn');
      if (submitBtn) {
        submitBtn.onclick = () => {
          const verdict = document.getElementById('validationVerdictSelect').value;
          const notes = document.getElementById('validationNotesInput').value || '';
          return previewController.submitValidation({
            detail,
            session,
            candidate: { head_sha: candSha, base_sha: baseSha, generation: candidateGeneration },
            scenarios,
            container: scenariosContainer,
            verdict,
            notes,
            allowed: validationAllowed,
            button: submitBtn,
          });
        };
      }
    }

    // Render Validation History
    const history = (previewVal && previewVal.validation_history) ? previewVal.validation_history : [];
    if (history.length === 0) {
      historyContainer.innerHTML = `<p class="text-muted" style="font-size: 12px;">No historical validation runs recorded.</p>`;
    } else {
      historyContainer.innerHTML = `
        <table class="data-table small-table">
          <thead>
            <tr>
              <th>Verdict</th>
              <th>Candidate SHA</th>
              <th>Image Digest</th>
              <th>Operator</th>
              <th>Recorded At</th>
              <th>Authority Status</th>
            </tr>
          </thead>
          <tbody>
            ${history.map(v => `
              <tr>
                <td><span class="badge ${v.verdict === 'PASS' ? 'badge-ready' : 'badge-failed'}">${escapeHtml(v.verdict)}</span></td>
                <td><code class="code-sha">${escapeHtml(v.head_sha_short || v.head_sha.substring(0, 8))}</code></td>
                <td><code class="code-sha">${escapeHtml(v.image_digest ? v.image_digest.substring(0, 15) + '...' : '---')}</code></td>
                <td>${escapeHtml(v.operator || 'operator')}</td>
                <td>${formatRelativeTime(v.created_at)}</td>
                <td>${v.is_stale ? '<span class="badge badge-warning">STALE</span>' : '<span class="text-success">CURRENT</span>'}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
    }
  }

  function renderGitHubTab(github, projectId) {

    const container = document.getElementById('githubDetailsContainer');
    if (!container) return;

    if (!github || (!github.issue_number && !github.pr_number)) {
      container.innerHTML = `<p class="text-muted">No hay un Issue o Pull Request de GitHub vinculado a este cambio.</p>`;
      return;
    }

    container.innerHTML = `
      <div class="overview-meta-grid">
        <div class="meta-box">
          <div class="meta-box-label">GitHub Issue</div>
          <div class="meta-box-val">${github.issue_url ? `<a href="${sanitizeUrl(github.issue_url)}" target="_blank" rel="noopener noreferrer" class="text-primary">#${github.issue_number} ↗</a>` : (github.issue_number ? `#${github.issue_number}` : '---')}</div>
        </div>
        <div class="meta-box">
          <div class="meta-box-label">Pull Request</div>
          <div class="meta-box-val">${github.pr_url ? `<a href="${sanitizeUrl(github.pr_url)}" target="_blank" rel="noopener noreferrer" class="text-primary">PR #${github.pr_number} ↗</a>` : (github.pr_number ? `PR #${github.pr_number}` : 'None created yet')}</div>
        </div>
        <div class="meta-box">
          <div class="meta-box-label">PR State</div>
          <div class="meta-box-val"><span class="badge ${github.is_merged ? 'badge-completed' : (github.pr_state === 'open' ? 'badge-ready' : 'badge-not-ready')}">${github.is_merged ? 'MERGED' : (github.pr_state ? github.pr_state.toUpperCase() : 'PENDING')}</span></div>
        </div>
        <div class="meta-box">
          <div class="meta-box-label">Candidate Bound</div>
          <div class="meta-box-val">${github.candidate_bound ? '<span class="text-success">✓ Bound</span>' : '<span class="text-muted">Pending</span>'}</div>
        </div>
      </div>
    `;
  }

  function renderTimelineTab(timeline) {
    const container = document.getElementById('timelineListContainer');
    if (!container) return;

    if (!timeline || timeline.length === 0) {
      container.innerHTML = `<p class="text-muted">No hay eventos del ciclo de vida para este cambio.</p>`;
      return;
    }

    container.innerHTML = timeline.map(e => `
      <div class="timeline-entry">
        <div class="timeline-time">${formatTimestamp(e.timestamp)}</div>
        <div class="timeline-title">${escapeHtml(e.summary)}</div>
        <div class="timeline-desc">Event: <span class="font-mono">${escapeHtml(e.event_type)}</span> | Actor: ${escapeHtml(e.actor || 'system')}</div>
      </div>
    `).join('');
  }

  // =========================================================================
  // 021 WORK INTAKE & PROJECT ONBOARDING CONTROLLERS
  // =========================================================================

  function switchMainView(viewName) {
    navigationController.switchView(viewName);
  }

  // Projects Operations
  function fetchProjects() { return projectsController.fetchProjects(); }

  // Backlog Operations
  async function fetchBacklog(projectId) {
    if (!projectId) {
      renderBacklogUnavailable();
      return;
    }
    updateAdmissionPolicy(null);
    try {
      // Fetch project details for admission policy
      try {
        const projResp = await fetch(`/api/v1/projects/${encodeURIComponent(projectId)}`);
        if (projResp.ok) {
          const proj = await projResp.json();
          updateAdmissionPolicy(proj);
        }
      } catch (e) {
        // Non-blocking project info fetch
      }

      const resp = await fetch(`/api/v1/projects/${encodeURIComponent(projectId)}/backlog`);
      if ([401, 403].includes(resp.status)) {
        sessionController.showLogin();
        return;
      }
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      backlogItems = await resp.json();
      renderBacklogTable();
      if (selectedBacklogItem) {
        const updated = backlogItems.find(i => i.item_key === selectedBacklogItem.item_key);
        if (updated) {
          selectBacklogItem(updated.item_key);
        } else if (backlogItems.length > 0) {
          selectBacklogItem(backlogItems[0].item_key);
        }
      } else if (backlogItems.length > 0) {
        selectBacklogItem(backlogItems[0].item_key);
      } else {
        if (backlogPlaceholder) backlogPlaceholder.style.display = 'flex';
        if (backlogDetailContent) backlogDetailContent.style.display = 'none';
      }
    } catch (err) {
      console.error('Failed fetching backlog:', err);
    }
  }

  function renderBacklogUnavailable() {
    backlogItems = [];
    updateAdmissionPolicy(null);
    if (backlogTableBody) {
      backlogTableBody.innerHTML = '<tr><td colspan="6" class="table-empty">Selecciona un proyecto autorizado para consultar su trabajo.</td></tr>';
    }
    if (backlogPlaceholder) {
      backlogPlaceholder.style.display = 'block';
      backlogPlaceholder.textContent = 'Selecciona un proyecto autorizado o registra uno desde Proyectos.';
    }
    if (backlogDetailContent) backlogDetailContent.style.display = 'none';
  }

  function updateAdmissionPolicy(project) {
    const renderBoolean = (element, label, value) => {
      if (!element) return;
      const known = typeof value === 'boolean';
      element.textContent = `${label}: ${known ? (value ? 'ACTIVADA' : 'DESACTIVADA') : 'DESCONOCIDO'}`;
      element.dataset.state = known ? 'KNOWN' : 'UNKNOWN';
      element.className = `badge ${known && value ? 'badge-info' : 'badge-muted'}`;
    };
    renderBoolean(document.getElementById('badgeAutoPrepare'), 'Preparación automática', project?.auto_prepare);
    renderBoolean(document.getElementById('badgeAutoAdmit'), 'Admisión automática', project?.auto_admit);

    const concurrency = document.getElementById('badgeConcurrency');
    const limit = project?.max_concurrent_jobs;
    const knownLimit = Number.isInteger(limit) && limit > 0;
    if (concurrency) {
      concurrency.textContent = `Concurrencia: ${knownLimit ? limit : 'DESCONOCIDO'}`;
      concurrency.dataset.state = knownLimit ? 'KNOWN' : 'UNKNOWN';
      concurrency.className = 'badge badge-muted';
    }
  }

  function renderBacklogTable() {
    renderBacklogTableView({
      root: backlogTableBody,
      items: backlogItems,
      filter: backlogController.filter,
      query: backlogController.searchQuery,
      selectedItem: selectedBacklogItem,
      escapeHtml,
      getStatusBadgeClass,
    });
  }

  function selectBacklogItem(itemKey) {
    const item = backlogItems.find(i => i.item_key === itemKey);
    if (!item) return;
    selectedBacklogItem = item;

    // Update row selections in table
    if (backlogTableBody) {
      const rows = backlogTableBody.querySelectorAll('tr[data-item-key]');
      rows.forEach(r => {
        r.classList.toggle('selected-row', r.getAttribute('data-item-key') === itemKey);
      });
    }

    renderBacklogDetail(item);
  }

  function renderBacklogDetail(item) {
    renderBacklogDetailView({
      item,
      elements: {
        placeholder: backlogPlaceholder,
        content: backlogDetailContent,
        title: bkTitle,
        status: bkStatusBadge,
        priority: bkPriorityBadge,
        key: bkKey,
        source: bkSource,
        readiness: bkReadiness,
        startButton: bkStartBtn,
        needsHumanCard: bkNeedsHumanCard,
        humanQuestionsList: bkHumanQuestionsList,
        description: bkDescriptionPreview,
        criteria: bkCriteriaList,
        dorOverall: bkDorOverallPill,
        dorGrid: bkDorGrid,
        openSpec: bkArtOpenSpec,
        issue: bkArtIssue,
        projectItem: bkArtProject,
        run: bkArtRun,
      },
      escapeHtml,
      sanitizeUrl,
      renderMarkdownText,
      getStatusBadgeClass,
    });
  }

  function openNewWorkItemModal(itemToEdit = null) {
    if (!newWorkItemModal) return;
    if (itemToEdit) {
      editingItemKey = itemToEdit.item_key;
      if (workItemModalTitle) workItemModalTitle.textContent = 'Edit Backlog Work Item';
      if (newWorkItemTitle) newWorkItemTitle.value = itemToEdit.title || '';
      if (newWorkItemKey) {
        newWorkItemKey.value = itemToEdit.item_key || '';
        newWorkItemKey.disabled = true;
      }
      if (newWorkItemPriority) newWorkItemPriority.value = itemToEdit.priority || 'NORMAL';
      if (newWorkItemDescription) newWorkItemDescription.value = itemToEdit.description || '';
      if (newWorkItemCriteria) newWorkItemCriteria.value = (itemToEdit.acceptance_criteria || []).join('\n');
    } else {
      editingItemKey = null;
      if (workItemModalTitle) workItemModalTitle.textContent = 'Create Backlog Work Item';
      if (newWorkItemForm) newWorkItemForm.reset();
      if (newWorkItemKey) newWorkItemKey.disabled = false;
    }
    newWorkItemModal.showModal();
  }

  async function saveWorkItem() {
    const title = newWorkItemTitle?.value.trim();
    const itemKey = newWorkItemKey?.value.trim();
    const priority = newWorkItemPriority?.value || 'NORMAL';
    const description = newWorkItemDescription?.value.trim() || '';
    const criteriaRaw = newWorkItemCriteria?.value.trim() || '';
    const criteria = criteriaRaw.split('\n').map(c => c.replace(/^[-*•]\s*/, '').trim()).filter(Boolean);

    if (!title) {
      showToast('Title is required', 'warning');
      return;
    }

    try {
      await backlogController.save({
        item_key: itemKey || undefined,
        title,
        priority,
        description,
        acceptance_criteria: criteria,
      }, editingItemKey);
      if (newWorkItemModal) newWorkItemModal.close();
    } catch (err) {
      showToast(`No se pudo guardar el trabajo: ${err.message}`, 'error');
    }
  }

  function renderMarkdownText(text) {
    if (!text) return '';
    const escaped = escapeHtml(text);
    return escaped
      .replace(/^### (.*$)/gim, '<h5>$1</h5>')
      .replace(/^## (.*$)/gim, '<h4>$1</h4>')
      .replace(/^# (.*$)/gim, '<h3>$1</h3>')
      .replace(/\*\*(.*?)\*\*/gim, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/gim, '<em>$1</em>')
      .replace(/`([^`]+)`/gim, '<code>$1</code>')
      .replace(/\n/gim, '<br>');
  }

  // Expose helper functions globally for inline handlers
  // Utilities
  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function sanitizeUrl(url) {
    if (!url) return '#';
    try {
      const parsed = new URL(String(url).trim(), window.location.origin);
      if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
        return escapeHtml(parsed.href);
      }
    } catch (_) {}
    return '#';
  }

  function formatRelativeTime(isoStr) {
    if (!isoStr) return '---';
    try {
      const dt = new Date(isoStr);
      const diffSec = Math.floor((Date.now() - dt.getTime()) / 1000);
      if (diffSec < 60) return `hace ${diffSec} s`;
      if (diffSec < 3600) return `hace ${Math.floor(diffSec / 60)} min`;
      if (diffSec < 86400) return `hace ${Math.floor(diffSec / 3600)} h`;
      return `hace ${Math.floor(diffSec / 86400)} d`;
    } catch {
      return isoStr;
    }
  }

  function formatTimestamp(isoStr) {
    if (!isoStr) return '---';
    try {
      const dt = new Date(isoStr);
      return dt.toLocaleTimeString() + ' ' + dt.toLocaleDateString();
    } catch {
      return isoStr;
    }
  }

  // The ES-module bootstrap in app.js is the only initialization owner.
