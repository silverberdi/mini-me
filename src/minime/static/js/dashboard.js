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
  function safeGetStorage(key, defaultVal) {
    try {
      return localStorage.getItem(key) || defaultVal;
    } catch (_) {
      return defaultVal;
    }
  }

  function safeSetStorage(key, val) {
    try {
      localStorage.setItem(key, val);
    } catch (_) {}
  }

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
  let activeFilter = 'ALL';
  let searchQuery = '';
  let refreshIntervalSeconds = parseInt(safeGetStorage('minime_dashboard_interval', '10'), 10);
  let countdownSeconds = refreshIntervalSeconds;
  let countdownInterval = null;

  // 021 Intake & Projects State
  let currentMainView = 'viewExecutions';
  let currentProjectId = null;
  let projectsList = [];
  let backlogItems = [];
  let selectedBacklogItem = null;
  let backlogFilter = 'ALL';
  let backlogSearchQuery = '';
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
  const sessionController = createSessionController({
    fetch,
    loginSection,
    authenticatedContent,
    profileGroup: operatorProfileGroup,
    emailNode: operatorEmailText,
    onAuthenticated: (operator) => { void initDesktopPaneLayout(operator.email); },
    onUnauthenticated: () => {
      clearInterval(countdownInterval);
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

  // Initialization
  export async function initDashboard() {
    themeController.initialize();
    sessionController.bindLogout(logoutBtn);
    setupEventListeners();
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => {});
    }
    const authenticated = await sessionController.checkAuth();
    if (authenticated) {
      await fetchProjects();
      switchMainView('viewExecutions');
      setupAutoRefresh();
    }
  }

  // Event Listeners
  function setupEventListeners() {
    window.addEventListener('resize', () => {
      const executions = document.getElementById('viewExecutions');
      if (executions?.classList.contains('active')) {
        executions.style.display = window.matchMedia('(min-width: 1200px)').matches ? 'grid' : 'block';
      }
    }, { passive: true });
    window.addEventListener('offline', () => {
      setOfflineBanner(true);
      ["overviewFreshness", "queueFreshness", "providerFreshness", "healthFreshness"].forEach((id) => {
        const node = document.getElementById(id);
        if (node) {
          node.textContent = "Sin conexión: la última lectura puede estar desactualizada.";
          node.dataset.state = "STALE";
        }
      });
    });
    window.addEventListener('online', () => {
      if (currentMainView === 'viewBacklog') fetchBacklog(currentProjectId);
      else if (currentMainView === 'viewProjects') fetchProjects();
      fetchOverview();
    });
    // 021 Main View Navigation
    mainNavTabs.forEach((tab) => {
      tab.addEventListener('click', () => {
        const targetView = tab.getAttribute('data-main-view');
        if (targetView) switchMainView(targetView);
      });
    });
    document.querySelectorAll('.bottom-nav [data-main-view]').forEach((tab) => {
      tab.addEventListener('click', () => {
        const targetView = tab.getAttribute('data-main-view');
        if (targetView) switchMainView(targetView);
      });
    });
    document.querySelectorAll('.bottom-nav [data-scroll-to]').forEach((button) => {
      button.addEventListener('click', () => {
        switchMainView('viewExecutions');
        const target = document.getElementById(button.getAttribute('data-scroll-to'));
        target?.scrollIntoView({
          behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
          block: 'start',
        });
      });
    });

    if (projectSelect) {
      projectSelect.addEventListener('change', (e) => {
        currentProjectId = e.target.value;
        if (backlogProjectDisplay) {
          backlogProjectDisplay.textContent = `Proyecto: ${currentProjectId}`;
        }
        if (currentMainView === 'viewBacklog') {
          fetchBacklog(currentProjectId);
        }
      });
    }

    // Backlog Search & Filter
    if (backlogSearchInput) {
      backlogSearchInput.addEventListener('input', (e) => {
        backlogSearchQuery = e.target.value.toLowerCase().trim();
        renderBacklogTable();
      });
    }

    backlogStatusPills.forEach((pill) => {
      pill.addEventListener('click', () => {
        backlogStatusPills.forEach((p) => p.classList.remove('active'));
        pill.classList.add('active');
        backlogFilter = pill.getAttribute('data-backlog-filter');
        renderBacklogTable();
      });
    });

    if (backlogTableBody) {
      backlogTableBody.addEventListener('click', (e) => {
        const actionButton = e.target.closest('[data-backlog-action]');
        if (actionButton) {
          e.stopPropagation();
          const itemKey = actionButton.dataset.itemKey;
          if (actionButton.dataset.backlogAction === 'prepare') void prepareBacklogItem(itemKey);
          if (actionButton.dataset.backlogAction === 'start') void startBacklogItem(itemKey);
          return;
        }
        const row = e.target.closest('[data-item-key]');
        if (row) {
          const itemKey = row.getAttribute('data-item-key');
          selectBacklogItem(itemKey);
        }
      });
    }

    projectsGridContainer?.addEventListener('click', (event) => {
      const button = event.target.closest('[data-project-action][data-project-id]');
      if (!button) return;
      const projectId = button.dataset.projectId;
      if (button.dataset.projectAction === 'inspect') void inspectContext(projectId);
      else if (button.dataset.projectAction === 'discover') void discoverBacklogContext(projectId);
      else if (button.dataset.projectAction === 'backlog') {
        currentProjectId = projectId;
        if (projectSelect) projectSelect.value = projectId;
        switchMainView('viewBacklog');
      }
    });

    bkArtRun?.addEventListener('click', (event) => {
      const button = event.target.closest('[data-open-run]');
      if (button?.dataset.openRun) switchMainView('viewExecutions');
    });

    // Backlog Action Buttons & Forms
    if (newWorkItemBtn) {
      newWorkItemBtn.addEventListener('click', () => {
        openNewWorkItemModal();
      });
    }

    if (cancelWorkItemBtn) {
      cancelWorkItemBtn.addEventListener('click', () => {
        if (newWorkItemModal) newWorkItemModal.close();
      });
    }

    if (newWorkItemForm) {
      newWorkItemForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        await saveWorkItem();
      });
    }

    if (discoverBacklogBtn) {
      discoverBacklogBtn.addEventListener('click', async () => {
        await discoverBacklogContext(currentProjectId);
      });
    }

    if (bkPrepareBtn) {
      bkPrepareBtn.addEventListener('click', async () => {
        if (selectedBacklogItem) {
          await prepareBacklogItem(selectedBacklogItem.item_key);
        }
      });
    }

    if (bkStartBtn) {
      bkStartBtn.addEventListener('click', async () => {
        if (selectedBacklogItem) {
          await startBacklogItem(selectedBacklogItem.item_key);
        }
      });
    }

    if (bkEditBtn) {
      bkEditBtn.addEventListener('click', () => {
        if (selectedBacklogItem) {
          openNewWorkItemModal(selectedBacklogItem);
        }
      });
    }

    if (bkDeleteBtn) {
      bkDeleteBtn.addEventListener('click', async () => {
        if (selectedBacklogItem) {
          await deleteWorkItem(selectedBacklogItem.item_key);
        }
      });
    }

    if (answerQuestionForm) {
      answerQuestionForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (selectedBacklogItem) {
          const answer = humanAnswerInput ? humanAnswerInput.value.trim() : '';
          if (answer) {
            await submitQuestionAnswer(selectedBacklogItem.item_key, answer);
          }
        }
      });
    }

    // Project Onboarding & Context Modals
    if (onboardProjectBtn) {
      onboardProjectBtn.addEventListener('click', () => {
        openOnboardModal();
      });
    }

    if (cancelOnboardBtn) {
      cancelOnboardBtn.addEventListener('click', () => {
        if (onboardProjectModal) onboardProjectModal.close();
      });
    }

    if (onboardProjectForm) {
      onboardProjectForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        await submitOnboardProject();
      });
    }

    if (closeContextModalBtn) {
      closeContextModalBtn.addEventListener('click', () => {
        if (projectContextModal) projectContextModal.close();
      });
    }

    if (refreshBtn) {
      refreshBtn.addEventListener('click', () => {
        if (currentMainView === 'viewBacklog') {
          fetchBacklog(currentProjectId);
        } else if (currentMainView === 'viewProjects') {
          fetchProjects();
        } else {
          fetchOverview();
        }
        resetCountdown();
      });
    }

    if (refreshIntervalSelect) {
      refreshIntervalSelect.value = String(refreshIntervalSeconds);
      refreshIntervalSelect.addEventListener('change', (e) => {
        refreshIntervalSeconds = parseInt(e.target.value, 10);
        safeSetStorage('minime_dashboard_interval', String(refreshIntervalSeconds));
        countdownSeconds = refreshIntervalSeconds;
        setupAutoRefresh();
      });
    }

    if (autoRefreshToggle) {
      autoRefreshToggle.addEventListener('change', () => {
        if (autoRefreshToggle.checked) {
          setupAutoRefresh();
        } else {
          clearInterval(countdownInterval);
          if (refreshTimer) refreshTimer.textContent = 'desactivada';
        }
      });
    }

    document.addEventListener('visibilitychange', () => {
      if (!document.hidden && autoRefreshToggle && autoRefreshToggle.checked) {
        resetCountdown();
      }
    });

    if (changeSearchInput) {
      changeSearchInput.addEventListener('input', (e) => {
        searchQuery = e.target.value.toLowerCase().trim();
        renderChangesTable();
      });
    }

    filterPills.forEach((pill) => {
      pill.addEventListener('click', () => {
        filterPills.forEach((p) => p.classList.remove('active'));
        pill.classList.add('active');
        activeFilter = pill.getAttribute('data-filter');
        renderChangesTable();
      });
    });

    detailTabs.forEach((tab) => {
      tab.addEventListener('click', () => {
        detailTabs.forEach((t) => {
          t.classList.remove('active');
          t.setAttribute('aria-selected', 'false');
        });
        tabPanes.forEach((p) => p.classList.remove('active'));

        tab.classList.add('active');
        tab.setAttribute('aria-selected', 'true');
        const targetId = tab.getAttribute('data-tab');
        const targetPane = document.getElementById(targetId);
        if (targetPane) targetPane.classList.add('active');
      });
    });

    if (attentionItemsContainer) {
      attentionItemsContainer.addEventListener('click', (e) => {
        const card = e.target.closest('[data-project-id]');
        if (card) {
          selectChange(card.getAttribute('data-project-id'), card.getAttribute('data-change-name'));
        }
      });
    }

    if (changesTableBody) {
      changesTableBody.addEventListener('click', (e) => {
        const row = e.target.closest('[data-project-id]');
        if (row) {
          selectChange(row.getAttribute('data-project-id'), row.getAttribute('data-change-name'));
        }
      });
    }

    if (copyShaBtn) {
      copyShaBtn.addEventListener('click', () => {
        if (dtCandidateSha && dtCandidateSha.textContent !== '---') {
          navigator.clipboard.writeText(dtCandidateSha.getAttribute('data-full-sha') || dtCandidateSha.textContent);
          copyShaBtn.textContent = '✓';
          setTimeout(() => { copyShaBtn.textContent = '📋'; }, 1500);
        }
      });
    }

  }

  // Auto-Refresh
  function setupAutoRefresh() {
    clearInterval(countdownInterval);
    countdownSeconds = refreshIntervalSeconds;
    if (refreshTimer) refreshTimer.textContent = `${countdownSeconds}s`;

    countdownInterval = setInterval(() => {
      if (!autoRefreshToggle.checked) return;
      if (document.hidden) return;
      countdownSeconds -= 1;
      if (countdownSeconds <= 0) {
        countdownSeconds = refreshIntervalSeconds;
        fetchOverview();
      }
      if (refreshTimer) refreshTimer.textContent = `${countdownSeconds}s`;
    }, 1000);
  }

  function resetCountdown() {
    countdownSeconds = refreshIntervalSeconds;
    if (refreshTimer) refreshTimer.textContent = `${countdownSeconds}s`;
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
      filter: activeFilter,
      query: searchQuery,
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
    renderActionToolbar(detail);
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

  async function renderActionToolbar(detail) {
    const toolbar = document.getElementById('actionToolbar');
    if (!toolbar) return;
    const runId = detail?.run_id;
    if (!runId) {
      toolbar.innerHTML = '';
      return;
    }
    try {
      const actions = await discoverActions(runId);
      if (!actions || !actions.length) {
        toolbar.innerHTML = '<span class="text-muted">No hay acciones disponibles</span>';
        return;
      }
      toolbar.innerHTML = actions.map(action => {
        const actionType = action.action || action.action_type;
        const isDanger = ['cancel', 'recover_locks'].includes(actionType.toLowerCase());
        const isPrimary = ['continue', 'resolve_gate'].includes(actionType.toLowerCase());
        const btnClass = isDanger ? 'btn-danger' : (isPrimary ? 'btn-primary' : 'btn-secondary');
        const disabledAttr = action.enabled === false ? 'disabled' : '';
        const tooltip = action.disabled_reason ? `title="${escapeHtml(action.disabled_reason)}"` : `title="${escapeHtml(action.description || '')}"`;
        return `<button type="button" class="btn btn-sm ${btnClass}" data-action="${escapeHtml(actionType)}" ${disabledAttr} ${tooltip}>${escapeHtml(action.display_name || actionType)}</button>`;
      }).join(' ');

      toolbar.querySelectorAll('[data-action]:not(:disabled)').forEach(button => {
        button.addEventListener('click', () => {
          const actionType = button.dataset.action;
          const action = actions.find(item => (item.action || item.action_type) === actionType);
          if (action) handleActionClick(action, detail);
        });
      });
    } catch (err) {
      toolbar.innerHTML = '<span class="text-muted">Acciones del operador no disponibles</span>';
    }
  }

  function handleActionClick(action, detail) {
    const actionType = (action.action || action.action_type || '').toLowerCase();

    if (actionType === 'reassign') {
      openParamModal({
        title: 'Reasignar ejecutor',
        description: `Selecciona el proveedor de ejecución para «${detail.change_name}».`,
        fields: [
          {
            name: 'executor',
            label: 'Ejecutor de destino',
            type: 'select',
            options: [
              { value: 'codex', label: 'Codex (implementación)' },
              { value: 'antigravity', label: 'Antigravity (supervisión)' }
            ],
            default: 'codex'
          },
          {
            name: 'rationale',
            label: 'Motivo de la reasignación (opcional)',
            type: 'text',
            placeholder: 'Explica el motivo del relevo…'
          }
        ],
        onSubmit: (params) => {
          executeOperatorAction(detail, 'REASSIGN', {
            target_executor: params.executor,
            rationale: params.rationale || ''
          });
        }
      });
    } else if (actionType === 'resolve_gate') {
      openParamModal({
        title: 'Resolver compuerta humana',
        description: `Resolver la compuerta de «${detail.change_name}» (${detail.human_gate || 'desconocida'}).`,
        fields: [
          {
            name: 'resolution',
            label: 'Decisión',
            type: 'select',
            options: [
              { value: 'APPROVED', label: 'Aprobar (continuar)' },
              { value: 'REJECTED', label: 'Rechazar (solicitar cambios)' },
              { value: 'OVERRIDDEN', label: 'Anular compuerta' }
            ],
            default: 'APPROVED'
          },
          {
            name: 'notes',
            label: 'Notas de la decisión',
            type: 'textarea',
            placeholder: 'Añade notas o el motivo de la decisión…'
          }
        ],
        onSubmit: (params) => {
          executeOperatorAction(detail, 'RESOLVE_GATE', {
            gate_action: params.resolution,
            operator_notes: params.notes || ''
          });
        }
      });
    } else if (actionType === 'retry') {
      openParamModal({
        title: 'Reintentar etapa',
        description: `Reintentar la etapa de «${detail.change_name}».`,
        fields: [
          {
            name: 'reason',
            label: 'Motivo del reintento (opcional)',
            type: 'text',
            placeholder: 'Motivo del reintento…'
          }
        ],
        onSubmit: (params) => {
          executeOperatorAction(detail, 'RETRY', {
            reason: params.reason || 'Operator manual retry'
          });
        }
      });
    } else if (action.requires_confirmation || ['cancel', 'recover_locks', 'reconcile_post_merge'].includes(actionType)) {
      openConfirmModal({
        title: action.display_name || `Confirm ${actionType.toUpperCase()}`,
        description: action.confirmation_prompt || action.description || `Confirm execution of ${action.display_name || actionType}.`,
        warning: actionType === 'cancel' ? 'Esto cancelará la ejecución activa y liberará sus recursos gobernados.' : (actionType === 'recover_locks' ? 'Esto intentará recuperar los bloqueos obsoletos de esta ejecución.' : ''),
        meta: {
          'Change': detail.change_name,
          'Run ID': detail.run_id ? detail.run_id.slice(0, 8) + '...' : '---',
          'Etapa actual': detail.current_stage || '—',
          'Nivel de riesgo': action.risk_level || 'UNKNOWN'
        },
        onConfirm: () => {
          executeOperatorAction(detail, action.action || action.action_type);
        }
      });
    } else {
      executeOperatorAction(detail, action.action || action.action_type);
    }
  }

  async function executeOperatorAction(detail, actionType, parameters = {}) {
    const runId = detail?.run_id;
    if (!runId) {
      showToast('No se puede ejecutar la acción: el cambio no tiene un Run activo.', 'error');
      return;
    }
    const payload = {
      action_request_id: crypto.randomUUID(),
      project_id: detail.project_id,
      change_name: detail.change_name,
      run_id: runId,
      action_type: actionType.toUpperCase(),
      parameters: parameters,
      actor_identity: sessionController.currentUser?.email || 'operator',
      source_interface: 'pwa',
      expected_stage: detail.current_stage || null,
      expected_generation: detail.candidate_authority?.generation || (detail.generation || null),
      expected_candidate_sha: detail.candidate_authority?.candidate_sha || (detail.candidate_sha || null),
      expected_human_gate: detail.human_gate || null,
      requested_at: new Date().toISOString()
    };

    try {
      showToast(`Ejecutando ${actionType}…`, 'info');
      const result = await executeAction(runId, payload);
      if (result.status === 'SUCCESS' || result.status === 'COMPLETED' || result.status === 'ACCEPTED' || result.success === true) {
        showToast(`Acción ${actionType} completada: ${result.summary || result.message || 'Ejecución finalizada'}`, 'success');
        await fetchOverview();
        if (selectedChange && selectedChange.projectId && selectedChange.changeName) {
          await fetchChangeDetail(selectedChange.projectId, selectedChange.changeName);
        }
      } else {
        const errMsg = result.summary || result.error_message || result.error_code || result.detail || result.message || 'La acción fue rechazada o falló.';
        showToast(`Falló la acción: ${errMsg}`, 'error');
        await fetchOverview();
        if (selectedChange && selectedChange.projectId && selectedChange.changeName) {
          await fetchChangeDetail(selectedChange.projectId, selectedChange.changeName);
        }
      }
    } catch (err) {
      const message = err.payload?.summary || err.payload?.error_message || err.payload?.error_code || err.message;
      showToast(`Falló la acción: ${message}`, 'error');
      await fetchOverview();
    }
  }

  async function renderEfficiencyTab(projectId, changeName) {
    const container = document.getElementById('efficiencyContentContainer');
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
      summary: document.getElementById('candidateAuthSummary'),
      history: document.getElementById('candidateHistoryTbody'),
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
    renderReviewEvidence({ container: document.getElementById('reviewContentContainer'), review, candidate });
  }

  function renderAuditTab(audit, candidate) {
    renderAuditEvidence({ container: document.getElementById('auditContentContainer'), audit, candidate });
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

    // Action buttons visibility
    if (session && (session.status === 'READY' || session.status === 'STARTING' || session.status === 'PROBING')) {
      if (launchBtn) launchBtn.style.display = 'none';
      if (teardownBtn) {
        teardownBtn.style.display = 'inline-block';
        teardownBtn.onclick = async () => {
          teardownBtn.disabled = true;
          teardownBtn.textContent = 'Tearing down...';
          try {
            await fetch(`/api/v1/previews/${session.preview_id}/teardown`, { method: 'POST' });
            fetchOverview();
          } catch (e) {
            alert(`Teardown failed: ${e}`);
          } finally {
            teardownBtn.disabled = false;
            teardownBtn.textContent = '⏹ Teardown';
          }
        };
      }
    } else {
      if (teardownBtn) teardownBtn.style.display = 'none';
      if (launchBtn) {
        launchBtn.style.display = 'inline-block';
        launchBtn.disabled = !previewIdentityValid;
        launchBtn.title = previewIdentityValid
          ? 'Crear vista previa para la identidad exacta del candidato'
          : 'No disponible: falta identidad verificable de candidato, base o generación';
        launchBtn.onclick = async () => {
          if (!previewIdentityValid) return;
          launchBtn.disabled = true;
          launchBtn.textContent = 'Building...';
          try {
            const buildRes = await fetch('/api/v1/previews/build', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                project_id: detail.project_id,
                change_name: detail.change_name,
                run_id: detail.run_id,
                head_sha: candSha,
                base_sha: baseSha,
                candidate_generation: candidateGeneration,
              })
            });
            if (!buildRes.ok) {
              const err = await buildRes.json();
              throw new Error(err.detail || 'Build failed');
            }
            const buildData = await buildRes.json();

            launchBtn.textContent = 'Starting container...';
            const startRes = await fetch('/api/v1/previews/start', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                preview_id: buildData.preview_id,
                internal_port: 8787,
                probe_health: true,
              })
            });
            if (!startRes.ok) {
              const err = await startRes.json();
              throw new Error(err.detail || 'Start failed');
            }
            fetchOverview();
          } catch (e) {
            alert(`Preview launch failed: ${e.message}`);
          } finally {
            launchBtn.disabled = false;
            launchBtn.textContent = '🚀 Launch Preview';
          }
        };
      }
    }

    // Render Preview Container Status Card
    if (!session) {
      statusContainer.innerHTML = `
        <div class="overview-meta-grid" style="margin-bottom: 8px;">
          <div class="meta-box">
            <div class="meta-box-label">Preview Requirement</div>
            <div class="meta-box-val">${isRequired ? '<span class="badge badge-warning">REQUIRED FOR MERGE</span>' : '<span class="text-muted">Optional</span>'}</div>
          </div>
          <div class="meta-box">
            <div class="meta-box-label">Status</div>
            <div class="meta-box-val"><span class="badge badge-discovered">NOT LAUNCHED</span></div>
          </div>
          <div class="meta-box">
            <div class="meta-box-label">Validation Verdict</div>
            <div class="meta-box-val"><span class="badge badge-not-ready">PENDING</span></div>
          </div>
        </div>
        <p class="text-muted" style="font-size: 12px; margin: 0;">Click "Launch Preview" to build and start an isolated container environment for this candidate.</p>
      `;
    } else {
      const isReady = session.status === 'READY';
      const statusBadgeClass = isReady ? 'badge-ready' : (session.status === 'FAILED' ? 'badge-failed' : 'badge-running');
      statusContainer.innerHTML = `
        <div class="overview-meta-grid" style="margin-bottom: 12px;">
          <div class="meta-box">
            <div class="meta-box-label">Preview Status</div>
            <div class="meta-box-val"><span class="badge ${statusBadgeClass}">${escapeHtml(session.status)}</span></div>
          </div>
          <div class="meta-box">
            <div class="meta-box-label">Live Preview URL</div>
            <div class="meta-box-val">
              ${session.preview_url ? `<a href="${sanitizeUrl(session.preview_url)}" target="_blank" rel="noopener noreferrer" class="text-primary font-mono font-bold">${escapeHtml(session.preview_url)} ↗</a>` : '<span class="text-muted">---</span>'}
            </div>
          </div>
          <div class="meta-box">
            <div class="meta-box-label">Allocated Port</div>
            <div class="meta-box-val font-mono">${session.allocated_port || '---'}</div>
          </div>
          <div class="meta-box">
            <div class="meta-box-label">Authority Verdict</div>
            <div class="meta-box-val">
              ${isAuthorized ? '<span class="badge badge-completed">VALIDATED PASS</span>' : (isStale ? '<span class="badge badge-warning">STALE (RE-VALIDATION REQUIRED)</span>' : '<span class="badge badge-not-ready">NEEDS VALIDATION</span>')}
            </div>
          </div>
        </div>
        <div class="meta-box" style="margin-bottom: 8px;">
          <div class="meta-box-label">Immutable Image Digest</div>
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
      scenariosContainer.innerHTML = `<p class="text-muted" style="font-size: 12px;">No specific validation scenarios defined for this change.</p>`;
    } else {
      scenariosContainer.innerHTML = `
        <div class="checks-list" style="margin-bottom: 16px;">
          ${scenarios.map((sc, scIdx) => `
            <div class="check-item" style="flex-direction: column; align-items: flex-start; gap: 6px;">
              <div style="display: flex; justify-content: space-between; width: 100%; align-items: center;">
                <div class="check-item-title font-bold">${escapeHtml(sc.title)}</div>
                <span class="badge badge-ready">Required</span>
              </div>
              <p style="font-size: 12px; margin: 0; color: var(--text-muted);">${escapeHtml(sc.description)}</p>
              ${sc.ordered_steps && sc.ordered_steps.length > 0 ? `
                <div style="margin-top: 4px; padding-left: 8px; font-size: 11px;">
                  ${sc.ordered_steps.map((st, stIdx) => `
                    <label style="display: flex; align-items: center; gap: 6px; margin: 3px 0; cursor: pointer;">
                      <input type="checkbox" class="scenario-step-check" data-scenario-id="${escapeHtml(sc.scenario_id)}" data-step-idx="${stIdx}" checked>
                      <span>${escapeHtml(st)}</span>
                    </label>
                  `).join('')}
                </div>
              ` : ''}
            </div>
          `).join('')}
        </div>

        <div class="validation-submission-form" style="background: var(--bg-card-sub); padding: 12px; border-radius: 6px; border: 1px solid var(--border-color);">
          <h5 style="margin: 0 0 10px 0; font-size: 13px;">Record Candidate Validation Verdict</h5>
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 10px;">
            <div>
              <label style="font-size: 11px; color: var(--text-muted); display: block; margin-bottom: 4px;">Verdict</label>
              <select id="validationVerdictSelect" style="width: 100%; padding: 6px; border-radius: 4px; border: 1px solid var(--border-color); background: var(--bg-input); color: var(--text-primary);">
                <option value="PASS" selected>PASS — Candidate Visually Verified</option>
                <option value="FAIL">FAIL — Visual Defects Observed</option>
              </select>
            </div>
            <div>
              <label style="font-size: 11px; color: var(--text-muted); display: block; margin-bottom: 4px;">Operator Identity</label>
              <input type="text" id="validationOperatorInput" value="human_operator" style="width: 100%; padding: 6px; border-radius: 4px; border: 1px solid var(--border-color); background: var(--bg-input); color: var(--text-primary);">
            </div>
          </div>
          <div style="margin-bottom: 10px;">
            <label style="font-size: 11px; color: var(--text-muted); display: block; margin-bottom: 4px;">Validation Notes / Observations</label>
            <textarea id="validationNotesInput" rows="2" placeholder="Document verified visual flows, layout checks, or defect notes..." style="width: 100%; padding: 6px; border-radius: 4px; border: 1px solid var(--border-color); background: var(--bg-input); color: var(--text-primary); font-size: 12px;"></textarea>
          </div>
          <button id="submitValidationBtn" class="btn btn-primary btn-sm">💾 Submit Validation Verdict</button>
        </div>
      `;

      // Wire submit button
      const submitBtn = document.getElementById('submitValidationBtn');
      if (submitBtn) {
        submitBtn.onclick = async () => {
          submitBtn.disabled = true;
          submitBtn.textContent = 'Submitting...';
          const verdict = document.getElementById('validationVerdictSelect').value;
          const operator = document.getElementById('validationOperatorInput').value || 'human_operator';
          const notes = document.getElementById('validationNotesInput').value || '';
          const imgDigest = session ? session.image_digest : '';

          try {
            const res = await fetch('/api/v1/validations/submit', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                project_id: detail.project_id,
                change_name: detail.change_name,
                run_id: detail.run_id,
                preview_id: session ? session.preview_id : null,
                candidate_generation: detail.candidate_authority ? detail.candidate_authority.generation : 1,
                head_sha: candSha,
                base_sha: baseSha,
                image_digest: imgDigest,
                verdict: verdict,
                operator: operator,
                notes: notes,
                scenario_results: scenarios.map(sc => ({ scenario_id: sc.scenario_id, status: verdict })),
              })
            });
            if (!res.ok) {
              const err = await res.json();
              throw new Error(err.detail || 'Validation submit failed');
            }
            alert(`Validation verdict '${verdict}' successfully recorded for candidate!`);
            fetchOverview();
          } catch (e) {
            alert(`Error submitting validation: ${e.message}`);
          } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = '💾 Submit Validation Verdict';
          }
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

    const container = document.getElementById('githubContentContainer');
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
    currentMainView = viewName;
    document.querySelectorAll('[data-main-view]').forEach((tab) => {
      const isTarget = tab.getAttribute('data-main-view') === viewName;
      tab.classList.toggle('active', isTarget);
      if (tab.hasAttribute('aria-selected')) {
        tab.setAttribute('aria-selected', isTarget ? 'true' : 'false');
      }
      if (tab.hasAttribute('aria-current')) {
        if (isTarget) tab.setAttribute('aria-current', 'page');
        else tab.removeAttribute('aria-current');
      }
    });

    mainViewPanes.forEach((pane) => {
      if (pane.id === viewName) {
        pane.style.display = viewName === 'viewExecutions'
          && window.matchMedia('(min-width: 1200px)').matches ? 'grid' : 'block';
        pane.classList.add('active');
      } else {
        pane.style.display = 'none';
        pane.classList.remove('active');
      }
    });

    if (viewName === 'viewBacklog') {
      if (currentProjectId) fetchBacklog(currentProjectId);
      else renderBacklogUnavailable();
    } else if (viewName === 'viewProjects') {
      fetchProjects();
    } else if (viewName === 'viewExecutions') {
      fetchOverview();
    }
  }

  // Projects Operations
  async function fetchProjects() {
    try {
      const resp = await fetch('/projects');
      if ([401, 403].includes(resp.status)) {
        sessionController.showLogin();
        return;
      }
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      projectsList = await resp.json();
      renderProjectSelect();
      if (currentMainView === 'viewProjects') {
        renderProjectsGrid();
      }
    } catch (err) {
      console.error('Failed to fetch projects:', err);
    }
  }

  function renderProjectSelect() {
    if (!projectSelect) return;
    currentProjectId = renderProjectSelectView(
      projectSelect,
      projectsList,
      projectSelect.value || currentProjectId,
    );
    if (backlogProjectDisplay) {
      backlogProjectDisplay.textContent = `Proyecto: ${currentProjectId || 'DESCONOCIDO'}`;
    }
  }

  function renderProjectsGrid() {
    renderProjectsGridView(projectsGridContainer, projectsList, currentProjectId);
  }

  function openOnboardModal() {
    if (!onboardProjectModal) return;
    if (onboardProjectForm) onboardProjectForm.reset();
    onboardProjectModal.showModal();
  }

  async function submitOnboardProject() {
    const projId = document.getElementById('onboardProjectId')?.value.trim();
    const projName = document.getElementById('onboardProjectName')?.value.trim();
    const repo = document.getElementById('onboardRepository')?.value.trim();
    const branch = document.getElementById('onboardBaseBranch')?.value.trim() || 'main';
    const openspecPath = document.getElementById('onboardOpenSpecPath')?.value.trim() || 'openspec';
    const roadmapPath = document.getElementById('onboardRoadmapPath')?.value.trim() || 'docs/ROADMAP.md';
    const backlogPath = document.getElementById('onboardBacklogPath')?.value.trim() || 'docs/ROADMAP.md';

    if (!repo) {
      showToast('Repository is required', 'warning');
      return;
    }

    try {
      const resp = await fetch('/api/v1/projects/onboard', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: projId || undefined,
          name: projName || undefined,
          repository: repo,
          base_branch: branch,
          openspec_path: openspecPath,
          roadmap_path: roadmapPath,
          backlog_path: backlogPath
        })
      });

      if (!resp.ok) {
        const errData = await resp.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${resp.status}`);
      }

      const result = await resp.json();
      showToast(`Project '${result.project.name}' onboarded successfully! Discovered ${result.discovered_items_count} backlog items.`, 'success');
      if (onboardProjectModal) onboardProjectModal.close();
      await fetchProjects();
      currentProjectId = result.project.id;
      if (projectSelect) projectSelect.value = currentProjectId;
      switchMainView('viewBacklog');
    } catch (err) {
      console.error('Failed onboarding project:', err);
      showToast(`Onboarding failed: ${err.message}`, 'error');
    }
  }

  async function inspectContext(projectId) {
    try {
      const resp = await fetch(`/api/v1/projects/${encodeURIComponent(projectId)}/context`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const report = await resp.json();
      renderContextReport(report);
      if (projectContextModal) projectContextModal.showModal();
    } catch (err) {
      console.error('Failed fetching context:', err);
      showToast(`Failed inspecting context: ${err.message}`, 'error');
    }
  }

  function renderContextReport(report) {
    if (ctxDiscoveredFacts) {
      if (!report.discovered_facts || report.discovered_facts.length === 0) {
        ctxDiscoveredFacts.innerHTML = '<p class="text-muted">No facts discovered.</p>';
      } else {
        ctxDiscoveredFacts.innerHTML = report.discovered_facts.map(f => `
          <div class="fact-card">
            <div class="fact-header">
              <span class="badge badge-discovered">${escapeHtml(f.fact_type)}</span>
              <span class="fact-source font-mono text-xs">${escapeHtml(f.source_file)}</span>
            </div>
            <div class="fact-content">${escapeHtml(f.content)}</div>
          </div>
        `).join('');
      }
    }

    if (ctxInferredStructure) {
      if (!report.inferred_structure || report.inferred_structure.length === 0) {
        ctxInferredStructure.innerHTML = '<li class="text-muted">No inferred milestones or waves.</li>';
      } else {
        ctxInferredStructure.innerHTML = report.inferred_structure.map(s => `
          <li>${escapeHtml(s)}</li>
        `).join('');
      }
    }

    if (ctxMissingContext) {
      if (!report.missing_context || report.missing_context.length === 0) {
        ctxMissingContext.innerHTML = '<li class="text-success">✓ No critical context gaps identified.</li>';
      } else {
        ctxMissingContext.innerHTML = report.missing_context.map(g => `
          <li class="text-warning">⚠️ ${escapeHtml(g)}</li>
        `).join('');
      }
    }
  }

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
      filter: backlogFilter,
      query: backlogSearchQuery,
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

  async function prepareBacklogItem(itemKey) {
    try {
      showToast(`Preparing artifacts for '${itemKey}'...`, 'info');
      const resp = await fetch(`/api/v1/projects/${encodeURIComponent(currentProjectId)}/backlog/${encodeURIComponent(itemKey)}/prepare`, {
        method: 'POST'
      });
      if (!resp.ok) {
        const errData = await resp.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${resp.status}`);
      }
      const result = await resp.json();
      showToast(`Artifacts generated! Status: ${result.status}`, result.status === 'READY' ? 'success' : 'warning');
      await fetchBacklog(currentProjectId);
      selectBacklogItem(itemKey);
    } catch (err) {
      console.error('Failed preparing work item:', err);
      showToast(`Preparation failed: ${err.message}`, 'error');
    }
  }

  async function startBacklogItem(itemKey) {
    try {
      showToast(`Admitting '${itemKey}' into autonomous scheduler...`, 'info');
      const resp = await fetch(`/api/v1/projects/${encodeURIComponent(currentProjectId)}/backlog/${encodeURIComponent(itemKey)}/start`, {
        method: 'POST'
      });
      if (!resp.ok) {
        const errData = await resp.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${resp.status}`);
      }
      const result = await resp.json();
      showToast(`Work started! Run ID: ${result.run_id}`, 'success');
      await fetchBacklog(currentProjectId);
      selectBacklogItem(itemKey);
      setTimeout(() => {
        switchMainView('viewExecutions');
      }, 1000);
    } catch (err) {
      console.error('Failed starting work item:', err);
      showToast(`Failed starting work item: ${err.message}`, 'error');
    }
  }

  async function submitQuestionAnswer(itemKey, answerText) {
    try {
      showToast('Submitting clarification...', 'info');
      const resp = await fetch(`/api/v1/projects/${encodeURIComponent(currentProjectId)}/backlog/${encodeURIComponent(itemKey)}/answer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ answer: answerText })
      });
      if (!resp.ok) {
        const errData = await resp.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${resp.status}`);
      }
      showToast('Clarification recorded! Re-evaluating readiness...', 'success');
      if (humanAnswerInput) humanAnswerInput.value = '';
      await fetchBacklog(currentProjectId);
      selectBacklogItem(itemKey);
    } catch (err) {
      console.error('Failed answering question:', err);
      showToast(`Failed submitting answer: ${err.message}`, 'error');
    }
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
      if (editingItemKey) {
        const resp = await fetch(`/api/v1/projects/${encodeURIComponent(currentProjectId)}/backlog/${encodeURIComponent(editingItemKey)}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            title,
            priority,
            description,
            acceptance_criteria: criteria
          })
        });
        if (!resp.ok) {
          const errData = await resp.json().catch(() => ({}));
          throw new Error(errData.detail || `HTTP ${resp.status}`);
        }
        showToast(`Work item '${editingItemKey}' updated!`, 'success');
        if (newWorkItemModal) newWorkItemModal.close();
        await fetchBacklog(currentProjectId);
        selectBacklogItem(editingItemKey);
      } else {
        const resp = await fetch(`/api/v1/projects/${encodeURIComponent(currentProjectId)}/backlog`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            item_key: itemKey || undefined,
            title,
            priority,
            description,
            acceptance_criteria: criteria
          })
        });
        if (!resp.ok) {
          const errData = await resp.json().catch(() => ({}));
          throw new Error(errData.detail || `HTTP ${resp.status}`);
        }
        const created = await resp.json();
        showToast(`Work item '${created.item_key}' created!`, 'success');
        if (newWorkItemModal) newWorkItemModal.close();
        await fetchBacklog(currentProjectId);
        selectBacklogItem(created.item_key);
      }
    } catch (err) {
      console.error('Failed saving work item:', err);
      showToast(`Failed saving work item: ${err.message}`, 'error');
    }
  }

  async function deleteWorkItem(itemKey) {
    if (!confirm(`Are you sure you want to delete work item '${itemKey}'?`)) return;
    try {
      const resp = await fetch(`/api/v1/projects/${encodeURIComponent(currentProjectId)}/backlog/${encodeURIComponent(itemKey)}`, {
        method: 'DELETE'
      });
      if (!resp.ok) {
        const errData = await resp.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${resp.status}`);
      }
      showToast(`Work item '${itemKey}' deleted.`, 'info');
      selectedBacklogItem = null;
      await fetchBacklog(currentProjectId);
    } catch (err) {
      console.error('Failed deleting work item:', err);
      showToast(`Delete failed: ${err.message}`, 'error');
    }
  }

  async function discoverBacklogContext(projectId) {
    try {
      showToast('Scanning repository context & roadmap...', 'info');
      const resp = await fetch(`/api/v1/projects/${encodeURIComponent(projectId)}/context/discover`, {
        method: 'POST'
      });
      if (!resp.ok) {
        const errData = await resp.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${resp.status}`);
      }
      const result = await resp.json();
      showToast(`Discovery complete! Discovered ${result.discovered_items_count} items.`, 'success');
      await fetchProjects();
      await fetchBacklog(projectId);
    } catch (err) {
      console.error('Failed discovering context:', err);
      showToast(`Discovery failed: ${err.message}`, 'error');
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
  function getStatusBadgeClass(status) {
    switch (status) {
      case 'READY': return 'badge-ready';
      case 'RUNNING': return 'badge-running';
      case 'WAITING': return 'badge-waiting';
      case 'NEEDS_HUMAN': return 'badge-needs-human';
      case 'COMPLETED': return 'badge-completed';
      case 'FAILED': return 'badge-failed';
      case 'NOT_READY': return 'badge-not-ready';
      default: return 'badge-discovered';
    }
  }

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
