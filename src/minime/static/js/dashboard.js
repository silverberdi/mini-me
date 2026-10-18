import { setOfflineBanner } from "./components/offline_banner.js";
import { initDesktopPaneLayout } from "./desktop_pane_layout.js";
import { openConfirmModal, openParamModal } from "./components/action_dialog.js";
import { createThemeController } from "./components/theme_controller.js";
import { createToastController } from "./components/toast.js";
import { createSessionController } from "./services/session_controller.js";
import { renderProjectSelect as renderProjectSelectView, renderProjectsGrid as renderProjectsGridView } from "./views/projects_view.js";
import { discoverActions, executeAction } from "./services/control_plane_client.js";
import { createActionController } from "./controllers/action_controller.js";
import { createDetailTelemetryController } from "./controllers/detail_telemetry_controller.js";
import { createDetailViewController } from "./controllers/detail_view_controller.js";
import { createExecutionViewController } from "./controllers/execution_view_controller.js";
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
const showToast = createToastController();

  // Safe Storage Helpers
  // State
  let executionViewController = null;
  let navigationController = null;
  let backlogController = null;
  let projectsController = null;

  // 021 Intake & Projects State
  let currentProjectId = null;

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
  const detailPanel = document.getElementById('detailPanel');
  const detailDrawerBackdrop = document.getElementById('detailDrawerBackdrop');
  const closeDetailDrawerButton = document.getElementById('closeDetailDrawer');
  let detailDrawerReturnFocus = null;
  let detailDrawerReturnIdentity = null;
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
      executionViewController?.clear();
      backlogController?.clear();
      projectsController?.clear();
      currentProjectId = null;
      setOfflineBanner(false);
    },
  });
  const actionController = createActionController({
    execute: executeAction,
    discover: discoverActions,
    notify: showToast,
    refreshOverview: fetchOverview,
    refreshSelectedDetail: () => executionViewController?.refreshSelectedDetail(),
    getActor: () => sessionController.currentUser?.email,
    toolbar: document.getElementById('actionToolbar'),
    escapeHtml,
    openParameters: openParamModal,
    openConfirmation: openConfirmModal,
  });
  const detailTelemetryController = createDetailTelemetryController({
    fetchRequest: fetch,
    efficiencyContainer: document.getElementById('efficiencyDetailsContainer'),
    historyContainer: document.getElementById('actionHistoryContentContainer'),
    formatTimestamp,
  });
  const previewController = createPreviewController({
    fetchRequest: fetch,
    notify: showToast,
    refresh: fetchOverview,
    getActor: () => sessionController.currentUser?.email,
  });
  const detailViewController = createDetailViewController({
    elements: {
      placeholder: detailPlaceholder,
      content: detailContent,
      changeName: dtChangeName,
      status: dtStatusBadge,
      project: dtProject,
      repository: dtRepository,
      stage: dtStage,
      generation: dtGeneration,
      candidateSha: dtCandidateSha,
      copyShaButton: copyShaBtn,
      pipeline: pipelineStepper,
      overviewMeta: document.getElementById('overviewMetaGrid'),
      blockerSection: document.getElementById('overviewBlockerSection'),
      blockers: document.getElementById('overviewBlockersList'),
      candidate: document.getElementById('candidateDetailsContainer'),
      candidateHistory: document.getElementById('candidateHistoryBody'),
      checkCount: document.getElementById('checksTabCount'),
      checks: document.getElementById('checksListContainer'),
      review: document.getElementById('reviewDetailsContainer'),
      audit: document.getElementById('auditDetailsContainer'),
      previewStatus: document.getElementById('previewContainerStatus'),
      previewScenarios: document.getElementById('guidedValidationContainer'),
      validationHistory: document.getElementById('validationHistoryContainer'),
      launchPreviewButton: document.getElementById('launchPreviewBtn'),
      teardownPreviewButton: document.getElementById('teardownPreviewBtn'),
      github: document.getElementById('githubDetailsContainer'),
      timeline: document.getElementById('timelineListContainer'),
    },
    previewActions: previewController,
    telemetryController: detailTelemetryController,
    actionController,
    escapeHtml,
    sanitizeUrl,
    formatRelativeTime,
    formatTimestamp,
    statusClass: getStatusBadgeClass,
  });
  executionViewController = createExecutionViewController({
    fetchRequest: fetch,
    elements: {
      queueList: document.getElementById("queueList"),
      providerGrid: document.getElementById("providerGrid"),
      overviewFreshness: document.getElementById("overviewFreshness"),
      queueFreshness: document.getElementById("queueFreshness"),
      providerFreshness: document.getElementById("providerFreshness"),
      activityFreshness: document.getElementById("activityFreshness"),
      activityList: document.getElementById("activityList"),
      healthFreshness: document.getElementById("healthFreshness"),
      dbHealthBadge,
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
    setDetailDrawerOpen: (open, identity = null) => {
      const desktop = window.matchMedia('(min-width: 1200px)').matches;
      const isOpen = Boolean(open && desktop);
      if (isOpen && !detailPanel?.classList.contains('drawer-open')) {
        detailDrawerReturnFocus = document.activeElement;
        detailDrawerReturnIdentity = identity ? {
          projectId: identity.project_id,
          changeName: identity.change_name,
        } : null;
      }
      detailPanel?.classList.toggle('drawer-open', isOpen);
      document.body.classList.toggle('detail-drawer-open', isOpen);
      if (detailDrawerBackdrop) detailDrawerBackdrop.hidden = !isOpen;
      if (isOpen) window.requestAnimationFrame(() => closeDetailDrawerButton?.focus());
    },
    setOfflineBanner,
    onUnauthorized: () => sessionController.showLogin(),
    getNavigationState: () => navigationController,
    renderDetail: (detail) => detailViewController.render(detail),
    statusClass: getStatusBadgeClass,
    formatRelativeTime,
  });
  backlogController = createBacklogController({
    fetchRequest: fetch,
    notify: showToast,
    getProjectId: () => currentProjectId,
    refreshProjects: fetchProjects,
    onUnauthorized: () => sessionController.showLogin(),
    onStarted: () => setTimeout(() => switchMainView('viewExecutions'), 1000),
    confirmAction: (message) => window.confirm(message),
    escapeHtml,
    sanitizeUrl,
    getStatusBadgeClass,
    onOpenRun: () => switchMainView('viewExecutions'),
    elements: {
      tableBody: backlogTableBody,
      placeholder: backlogPlaceholder,
      autoPrepare: document.getElementById('badgeAutoPrepare'),
      autoAdmit: document.getElementById('badgeAutoAdmit'),
      concurrency: document.getElementById('badgeConcurrency'),
      detail: {
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
        answerTarget: answerQuestionTarget,
        description: bkDescriptionPreview,
        criteria: bkCriteriaList,
        dorOverall: bkDorOverallPill,
        dorGrid: bkDorGrid,
        openSpec: bkArtOpenSpec,
        issue: bkArtIssue,
        projectItem: bkArtProject,
        run: bkArtRun,
      },
    },
    workItemForm: {
      modal: newWorkItemModal,
      form: newWorkItemForm,
      title: workItemModalTitle,
      itemTitle: newWorkItemTitle,
      itemKey: newWorkItemKey,
      priority: newWorkItemPriority,
      description: newWorkItemDescription,
      criteria: newWorkItemCriteria,
    },
  });
  projectsController = createProjectsController({
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
    detailCloseButton: closeDetailDrawerButton,
    detailBackdrop: detailDrawerBackdrop,
    closeDetailDrawer: () => {
      if (!detailPanel?.classList.contains('drawer-open')) return false;
      detailPanel.classList.remove('drawer-open');
      document.body.classList.remove('detail-drawer-open');
      if (detailDrawerBackdrop) detailDrawerBackdrop.hidden = true;
      window.requestAnimationFrame(() => {
        if (detailDrawerReturnIdentity) {
          const returnTarget = document.querySelector('#changesTableBody tr.selected')
            || [...document.querySelectorAll('[data-project-id][data-change-name]')]
            .find((node) => node.dataset.projectId === detailDrawerReturnIdentity.projectId
              && node.dataset.changeName === detailDrawerReturnIdentity.changeName);
          if (returnTarget) {
            returnTarget.focus();
            return;
          }
        }
        if (detailDrawerReturnFocus instanceof HTMLElement && detailDrawerReturnFocus.isConnected) {
          detailDrawerReturnFocus.focus();
        }
      });
      return true;
    },
    candidateShaNode: dtCandidateSha,
    fetchBacklog: () => currentProjectId ? fetchBacklog(currentProjectId) : backlogController.renderUnavailable(),
    fetchProjects,
    fetchOverview,
    renderBacklogUnavailable: () => backlogController.renderUnavailable(),
    renderChangesTable: () => executionViewController.renderChangesTable(),
    selectChange: (...identity) => executionViewController.selectChange(...identity),
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
      answerTarget: answerQuestionTarget,
      runArtifact: bkArtRun,
      clearAnswer: () => {
        if (humanAnswerInput) humanAnswerInput.value = '';
        if (answerQuestionTarget) answerQuestionTarget.value = '';
      },
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

  function fetchOverview() { return executionViewController.refresh(); }

  // =========================================================================
  // 021 WORK INTAKE & PROJECT ONBOARDING CONTROLLERS
  // =========================================================================

  function switchMainView(viewName) {
    navigationController.switchView(viewName);
  }

  // Projects Operations
  function fetchProjects() { return projectsController.fetchProjects(); }

  // Backlog Operations
  function fetchBacklog(projectId) { return backlogController.load(projectId); }

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
