/**
 * mini me — Operations Dashboard Application Logic
 */

(function () {
  'use strict';

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
  let selectedChange = null;
  let initialSelected = false;
  let activeFilter = 'ALL';
  let searchQuery = '';
  let refreshIntervalSeconds = parseInt(safeGetStorage('minime_dashboard_interval', '10'), 10);
  let countdownSeconds = refreshIntervalSeconds;
  let countdownInterval = null;

  // 021 Intake & Projects State
  let currentMainView = 'viewBacklog';
  let currentProjectId = 'mini-me';
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
  const themeToggleBtn = document.getElementById('themeToggleBtn');
  const themeIcon = document.getElementById('themeIcon');
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
  let currentUser = null;
  const loginSection = document.getElementById('loginSection');
  const authenticatedContent = document.getElementById('authenticatedContent');
  const operatorProfileGroup = document.getElementById('operatorProfileGroup');
  const operatorEmailText = document.getElementById('operatorEmailText');
  const logoutBtn = document.getElementById('logoutBtn');

  // Initialization
  async function init() {
    setupTheme();
    setupEventListeners();
    const authenticated = await checkAuth();
    if (authenticated) {
      await fetchProjects();
      await fetchBacklog(currentProjectId);
      fetchOverview();
      setupAutoRefresh();
    }
  }

  // Authentication State Management
  async function checkAuth() {
    try {
      const resp = await fetch('/api/v1/auth/me');
      if (resp.ok) {
        const data = await resp.json();
        if (data.authenticated && data.operator) {
          currentUser = data.operator;
          showAuthenticatedUI();
          return true;
        }
      }
    } catch (e) {
      console.error('Failed checking authentication:', e);
    }
    showLoginUI();
    return false;
  }

  function showAuthenticatedUI() {
    if (loginSection) loginSection.style.display = 'none';
    if (authenticatedContent) authenticatedContent.style.display = 'block';
    if (operatorProfileGroup) {
      operatorProfileGroup.style.display = 'flex';
      if (operatorEmailText && currentUser) {
        operatorEmailText.textContent = currentUser.email;
      }
    }
  }

  function showLoginUI() {
    currentUser = null;
    if (authenticatedContent) authenticatedContent.style.display = 'none';
    if (operatorProfileGroup) operatorProfileGroup.style.display = 'none';
    if (loginSection) loginSection.style.display = 'flex';
    clearInterval(countdownInterval);
  }

  async function handleLogout() {
    try {
      await fetch('/api/v1/auth/logout', { method: 'POST' });
    } catch (err) {
      console.error('Logout error:', err);
    }
    showLoginUI();
  }

  // Theme Handling
  function setupTheme() {
    let savedTheme = safeGetStorage('minime_theme', null);
    if (!savedTheme) {
      const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
      savedTheme = prefersDark ? 'theme-dark' : 'theme-light';
    }
    document.body.className = savedTheme;
    updateThemeIcon(savedTheme);
  }

  function toggleTheme() {
    const isDark = document.body.classList.contains('theme-dark');
    const newTheme = isDark ? 'theme-light' : 'theme-dark';
    document.body.className = newTheme;
    safeSetStorage('minime_theme', newTheme);
    updateThemeIcon(newTheme);
  }

  function updateThemeIcon(theme) {
    if (themeIcon) {
      themeIcon.textContent = theme === 'theme-light' ? '🌙' : '☀️';
    }
  }

  // Event Listeners
  function setupEventListeners() {
    // 021 Main View Navigation
    mainNavTabs.forEach((tab) => {
      tab.addEventListener('click', () => {
        const targetView = tab.getAttribute('data-main-view');
        if (targetView) switchMainView(targetView);
      });
    });

    if (projectSelect) {
      projectSelect.addEventListener('change', (e) => {
        currentProjectId = e.target.value;
        if (backlogProjectDisplay) {
          backlogProjectDisplay.textContent = `Project: ${currentProjectId}`;
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
        const row = e.target.closest('[data-item-key]');
        if (row) {
          const itemKey = row.getAttribute('data-item-key');
          selectBacklogItem(itemKey);
        }
      });
    }

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

    if (themeToggleBtn) {
      themeToggleBtn.addEventListener('click', toggleTheme);
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
          if (refreshTimer) refreshTimer.textContent = 'off';
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

    if (logoutBtn) {
      logoutBtn.addEventListener('click', () => {
        handleLogout();
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
    try {
      const resp = await fetch('/api/v1/dashboard/overview');
      if (resp.status === 401) {
        showLoginUI();
        return;
      }
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      overviewData = await resp.json();
      renderOverview();
      if (selectedChange) {
        fetchChangeDetail(selectedChange.project_id, selectedChange.change_name);
      }
    } catch (err) {
      console.error('Failed to fetch overview:', err);
    }
  }

  async function fetchChangeDetail(projectId, changeName) {
    try {
      const resp = await fetch(`/api/v1/dashboard/changes/${encodeURIComponent(projectId)}/${encodeURIComponent(changeName)}`);
      if (resp.status === 401) {
        showLoginUI();
        return;
      }
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const detailData = await resp.json();
      renderDetail(detailData);
    } catch (err) {
      console.error('Failed to fetch change detail:', err);
    }
  }

  // Rendering
  function renderOverview() {
    if (!overviewData) return;

    const { system_status, attention_items, active_executions, recent_completions, changes } = overviewData;

    // Header Indicators
    if (schedulerModeBadge) {
      schedulerModeBadge.innerHTML = `<span class="dot ${system_status.scheduler_mode === 'RUN' ? 'dot-success' : 'dot-warning'}"></span> MODE: ${system_status.scheduler_mode}`;
    }
    if (dbHealthBadge) {
      dbHealthBadge.innerHTML = `<span class="dot ${system_status.database_healthy ? 'dot-success' : 'dot-danger'}"></span> DB: ${system_status.database_healthy ? 'HEALTHY' : 'UNHEALTHY'}`;
    }

    // KPI Cards
    if (kpiSystemStateVal) {
      kpiSystemStateVal.textContent = system_status.healthy ? 'HEALTHY' : 'DEGRADED';
      kpiSystemStateVal.className = `kpi-value ${system_status.healthy ? 'text-success' : 'text-danger'}`;
    }
    if (kpiSystemStateSub) {
      kpiSystemStateSub.textContent = `Scheduler in active ${system_status.scheduler_mode} mode`;
    }

    if (kpiAttentionVal) {
      const count = attention_items ? attention_items.length : 0;
      kpiAttentionVal.textContent = count;
      kpiAttentionVal.className = `kpi-value ${count > 0 ? 'text-warning' : 'text-muted'}`;
    }
    if (kpiAttentionSub) {
      kpiAttentionSub.textContent = `${attention_items ? attention_items.length : 0} human gates / blockers`;
    }

    if (kpiActiveVal) {
      kpiActiveVal.textContent = active_executions ? active_executions.length : 0;
    }
    if (kpiActiveSub) {
      kpiActiveSub.textContent = `${active_executions ? active_executions.length : 0} changes currently in-flight`;
    }

    if (kpiCompletedVal) {
      const completedCount = changes.filter(c => c.status === 'COMPLETED').length;
      kpiCompletedVal.textContent = completedCount;
    }
    if (kpiCompletedSub) {
      kpiCompletedSub.textContent = `Total discovered: ${changes.length}`;
    }

    // Attention Banner
    if (attention_items && attention_items.length > 0) {
      attentionBanner.style.display = 'block';
      attentionCountText.textContent = `${attention_items.length} run${attention_items.length > 1 ? 's' : ''}`;
      attentionItemsContainer.innerHTML = attention_items.map(item => `
        <div class="attention-item-card" data-project-id="${escapeHtml(item.project_id)}" data-change-name="${escapeHtml(item.change_name)}">
          <div class="attention-item-left">
            <span class="attention-item-name">${escapeHtml(item.project_id)} / ${escapeHtml(item.change_name)}</span>
            <span class="attention-item-reason">${escapeHtml(item.reason)}</span>
          </div>
          <span class="badge badge-needs-human">${escapeHtml(item.stop_outcome || item.stage)}</span>
        </div>
      `).join('');
    } else {
      attentionBanner.style.display = 'none';
    }

    // Changes Table
    renderChangesTable();
  }

  function renderChangesTable() {
    if (!overviewData || !overviewData.changes) return;

    let list = overviewData.changes;

    // Apply Filter
    if (activeFilter === 'ATTENTION') {
      list = list.filter(c => c.status === 'NEEDS_HUMAN' || c.status === 'WAITING');
    } else if (activeFilter === 'RUNNING') {
      list = list.filter(c => c.status === 'RUNNING');
    } else if (activeFilter === 'READY') {
      list = list.filter(c => c.status === 'READY');
    } else if (activeFilter === 'COMPLETED') {
      list = list.filter(c => c.status === 'COMPLETED');
    }

    // Apply Search
    if (searchQuery) {
      list = list.filter(c =>
        c.change_name.toLowerCase().includes(searchQuery) ||
        c.project_id.toLowerCase().includes(searchQuery) ||
        c.status.toLowerCase().includes(searchQuery)
      );
    }

    if (list.length === 0) {
      changesTableBody.innerHTML = `<tr><td colspan="6" class="table-empty">No matching changes found.</td></tr>`;
      return;
    }

    changesTableBody.innerHTML = list.map(c => {
      const isSelected = selectedChange && selectedChange.project_id === c.project_id && selectedChange.change_name === c.change_name;
      const statusClass = getStatusBadgeClass(c.status);
      const shortSha = c.candidate_sha_short || '---';
      const updated = formatRelativeTime(c.updated_at);

      return `
        <tr class="${isSelected ? 'selected' : ''}" data-project-id="${escapeHtml(c.project_id)}" data-change-name="${escapeHtml(c.change_name)}">
          <td><span class="badge ${statusClass}">${escapeHtml(c.status)}</span></td>
          <td><strong>${escapeHtml(c.change_name)}</strong></td>
          <td>${escapeHtml(c.project_id)}</td>
          <td><span class="text-muted">${escapeHtml(c.stop_outcome || c.current_stage || '---')}</span></td>
          <td><code class="code-sha">${escapeHtml(shortSha)}</code></td>
          <td class="text-muted">${escapeHtml(updated)}</td>
        </tr>
      `;
    }).join('');

    // Auto-select first change only on initial page load if none selected
    if (!initialSelected && !selectedChange && list.length > 0) {
      initialSelected = true;
      selectChange(list[0].project_id, list[0].change_name);
    }
  }

  // Global Change Selector
  window.selectChange = function (projectId, changeName) {
    selectedChange = { project_id: projectId, change_name: changeName };
    renderChangesTable();
    fetchChangeDetail(projectId, changeName);
  };

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
    renderReviewTab(detail.review);

    // Tab 5: Audit
    renderAuditTab(detail.audit);

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
      const response = await fetch(`/api/v1/control-plane/actions/available?run_id=${encodeURIComponent(runId)}`);
      if (!response.ok) {
        toolbar.innerHTML = '<span class="text-muted">No actions available</span>';
        return;
      }
      const actions = await response.json();
      if (!actions || !actions.length) {
        toolbar.innerHTML = '<span class="text-muted">No actions available</span>';
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
      toolbar.innerHTML = '<span class="text-muted">Operator actions unavailable</span>';
    }
  }

  function handleActionClick(action, detail) {
    const actionType = (action.action || action.action_type || '').toLowerCase();

    if (actionType === 'reassign') {
      openParamModal({
        title: 'Reassign Executor',
        description: `Select target execution provider for '${detail.change_name}'.`,
        fields: [
          {
            name: 'executor',
            label: 'Target Executor',
            type: 'select',
            options: [
              { value: 'codex', label: 'Codex (Routine Implementation Workhorse)' },
              { value: 'antigravity', label: 'Antigravity (Supervisor & Governor)' }
            ],
            default: 'codex'
          },
          {
            name: 'rationale',
            label: 'Reassignment Rationale (Optional)',
            type: 'text',
            placeholder: 'Reason for handoff...'
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
        title: 'Resolve Human Gate',
        description: `Resolve gate for '${detail.change_name}' (Current Gate: ${detail.human_gate || 'Attention'}).`,
        fields: [
          {
            name: 'resolution',
            label: 'Decision',
            type: 'select',
            options: [
              { value: 'APPROVED', label: 'Approve (Proceed to next stage)' },
              { value: 'REJECTED', label: 'Reject (Require changes)' },
              { value: 'OVERRIDDEN', label: 'Override Gate' }
            ],
            default: 'APPROVED'
          },
          {
            name: 'notes',
            label: 'Resolution Notes',
            type: 'textarea',
            placeholder: 'Enter notes or reason for resolution...'
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
        title: 'Retry Stage',
        description: `Retry execution stage for '${detail.change_name}'.`,
        fields: [
          {
            name: 'reason',
            label: 'Retry Reason (Optional)',
            type: 'text',
            placeholder: 'Reason for stage retry...'
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
        warning: actionType === 'cancel' ? 'This will immediately abort the active run and clean active resources.' : (actionType === 'recover_locks' ? 'This will recover any stale locks held for this run.' : ''),
        meta: {
          'Change': detail.change_name,
          'Run ID': detail.run_id ? detail.run_id.slice(0, 8) + '...' : '---',
          'Current Stage': detail.current_stage || '---',
          'Risk Level': action.risk_level || 'STANDARD'
        },
        onConfirm: () => {
          executeOperatorAction(detail, action.action || action.action_type);
        }
      });
    } else {
      executeOperatorAction(detail, action.action || action.action_type);
    }
  }

  function openConfirmModal({ title, description, warning, meta, onConfirm }) {
    const dialog = document.getElementById('actionDialog');
    if (!dialog) return onConfirm();
    dialog.querySelector('[data-dialog-title]').textContent = title;
    dialog.querySelector('[data-dialog-description]').textContent = description;

    const warnBanner = document.getElementById('dialogWarningBanner');
    if (warnBanner) {
      if (warning) {
        warnBanner.textContent = '⚠️ ' + warning;
        warnBanner.style.display = 'block';
      } else {
        warnBanner.style.display = 'none';
      }
    }

    const metaBox = document.getElementById('dialogMetaInfo');
    if (metaBox) {
      if (meta && Object.keys(meta).length > 0) {
        metaBox.innerHTML = Object.entries(meta).map(([k, v]) => `<div><strong>${escapeHtml(k)}:</strong> ${escapeHtml(v)}</div>`).join('');
        metaBox.style.display = 'grid';
      } else {
        metaBox.style.display = 'none';
      }
    }

    dialog.showModal();
    const confirmBtn = document.getElementById('confirmActionBtn');
    confirmBtn.onclick = () => {
      dialog.close();
      onConfirm();
    };
    dialog.querySelector('[data-cancel]').onclick = () => dialog.close();
  }

  function openParamModal({ title, description, fields, onSubmit }) {
    const dialog = document.getElementById('actionParamDialog');
    if (!dialog) return;
    document.getElementById('paramDialogTitle').textContent = title;
    const body = document.getElementById('paramDialogBody');
    body.innerHTML = `
      <p class="dialog-desc">${escapeHtml(description)}</p>
      <form id="paramModalForm" class="param-form">
        ${fields.map(f => {
          if (f.type === 'select') {
            return `
              <div class="form-group">
                <label for="field_${f.name}">${escapeHtml(f.label)}</label>
                <select id="field_${f.name}" name="${f.name}" class="form-control">
                  ${f.options.map(opt => `<option value="${opt.value}" ${opt.value === f.default ? 'selected' : ''}>${escapeHtml(opt.label)}</option>`).join('')}
                </select>
              </div>
            `;
          } else if (f.type === 'textarea') {
            return `
              <div class="form-group">
                <label for="field_${f.name}">${escapeHtml(f.label)}</label>
                <textarea id="field_${f.name}" name="${f.name}" class="form-control" rows="3" placeholder="${escapeHtml(f.placeholder || '')}"></textarea>
              </div>
            `;
          } else {
            return `
              <div class="form-group">
                <label for="field_${f.name}">${escapeHtml(f.label)}</label>
                <input type="text" id="field_${f.name}" name="${f.name}" class="form-control" placeholder="${escapeHtml(f.placeholder || '')}" value="${escapeHtml(f.default || '')}">
              </div>
            `;
          }
        }).join('')}
      </form>
    `;

    dialog.showModal();
    const submitBtn = document.getElementById('submitParamActionBtn');
    submitBtn.onclick = (e) => {
      e.preventDefault();
      const form = document.getElementById('paramModalForm');
      const formData = new FormData(form);
      const params = {};
      for (const [k, v] of formData.entries()) {
        params[k] = v;
      }
      dialog.close();
      onSubmit(params);
    };
    dialog.querySelector('[data-param-cancel]').onclick = () => dialog.close();
  }

  async function executeOperatorAction(detail, actionType, parameters = {}) {
    const runId = detail?.run_id;
    if (!runId) {
      showToast('Cannot execute action: No active run for this change.', 'error');
      return;
    }
    const payload = {
      action_request_id: crypto.randomUUID(),
      project_id: detail.project_id,
      change_name: detail.change_name,
      run_id: runId,
      action_type: actionType.toUpperCase(),
      parameters: parameters,
      actor_identity: currentUser?.email || 'operator',
      source_interface: 'pwa',
      expected_stage: detail.current_stage || null,
      expected_generation: detail.candidate_authority?.generation || (detail.generation || null),
      expected_candidate_sha: detail.candidate_authority?.candidate_sha || (detail.candidate_sha || null),
      expected_human_gate: detail.human_gate || null,
      requested_at: new Date().toISOString()
    };

    try {
      showToast(`Executing ${actionType}...`, 'info');
      const response = await fetch('/api/v1/control-plane/actions/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const result = await response.json();
      if (response.ok && (result.status === 'SUCCESS' || result.success)) {
        showToast(`Action ${actionType} succeeded: ${result.message || 'Execution completed'}`, 'success');
        await fetchOverview();
        if (selectedChange && selectedChange.projectId && selectedChange.changeName) {
          await fetchChangeDetail(selectedChange.projectId, selectedChange.changeName);
        }
      } else {
        const errMsg = result.error_message || result.detail || result.message || 'Action rejected or failed.';
        showToast(`Action failed: ${errMsg}`, 'error');
        await fetchOverview();
        if (selectedChange && selectedChange.projectId && selectedChange.changeName) {
          await fetchChangeDetail(selectedChange.projectId, selectedChange.changeName);
        }
      }
    } catch (err) {
      showToast(`Network error executing action: ${err.message}`, 'error');
    }
  }

  async function renderEfficiencyTab(projectId, changeName) {
    const container = document.getElementById('efficiencyContentContainer');
    if (!container) return;
    if (!projectId || !changeName) {
      container.innerHTML = '<p class="table-empty">No telemetry recorded for this change.</p>';
      return;
    }
    try {
      const resp = await fetch(`/api/v1/efficiency/${encodeURIComponent(projectId)}/${encodeURIComponent(changeName)}`);
      if (!resp.ok) {
        container.innerHTML = '<p class="table-empty">No provider efficiency telemetry recorded for this change.</p>';
        return;
      }
      const data = await resp.json();
      const metrics = data.metrics || data;
      const productive = metrics.productive_attempt_count ?? (data.productive_attempt_ratio ? 1 : 0);
      const noProgress = metrics.no_progress_attempt_count ?? 0;
      const total = productive + noProgress;
      const ratio = total > 0 ? ((productive / total) * 100).toFixed(0) + '%' : (data.productive_attempt_ratio !== undefined ? (Number(data.productive_attempt_ratio) * 100).toFixed(0) + '%' : '100%');
      const attempts = total > 0 ? total : (data.total_attempts ?? 1);
      const reworks = metrics.corrective_retry_count ?? (data.rework_attempts ?? 0);
      const model = data.primary_model || (data.provider_summary?.[0]?.provider || 'codex');
      const reviewerModel = data.reviewer_model || (data.provider_summary?.[1]?.provider || 'antigravity');
      const indStatus = data.reviewer_independence !== false ? 'PASS' : 'INDEPENDENT';
      const selfHost = metrics.self_hosting_percentage !== undefined ? `${metrics.self_hosting_percentage.toFixed(0)}%` : '100%';

      container.innerHTML = `
        <div class="efficiency-kpi-grid">
          <div class="stat-card">
            <div class="stat-label">PRODUCTIVE ATTEMPTS</div>
            <div class="stat-value text-success">${escapeHtml(ratio)}</div>
            <div class="stat-sub">${attempts} total attempts (${reworks} corrective retries)</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">PRIMARY IMPLEMENTER</div>
            <div class="stat-value">${escapeHtml(model)}</div>
            <div class="stat-sub">Routine workhorse</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">COMPLEMENTARY REVIEWER</div>
            <div class="stat-value">${escapeHtml(reviewerModel)}</div>
            <div class="stat-sub">Independence: <strong class="text-success">${escapeHtml(indStatus)}</strong></div>
          </div>
          <div class="stat-card">
            <div class="stat-label">SELF-HOSTING NATIVE</div>
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
      container.innerHTML = '<p class="table-empty">Failed loading efficiency telemetry.</p>';
    }
  }

  async function renderActionHistoryTab(runId) {
    const container = document.getElementById('actionHistoryContentContainer');
    if (!container) return;
    if (!runId) {
      container.innerHTML = '<p class="table-empty">No action history for this execution run.</p>';
      return;
    }
    try {
      const resp = await fetch(`/api/v1/runs/${encodeURIComponent(runId)}/actions/history`);
      if (!resp.ok) {
        container.innerHTML = '<p class="table-empty">No operator actions have been performed on this run.</p>';
        return;
      }
      const history = await resp.json();
      if (!history || !history.length) {
        container.innerHTML = '<p class="table-empty">No operator actions recorded for this run yet.</p>';
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
      container.innerHTML = '<p class="table-empty">Failed loading action audit trail.</p>';
    }
  }


  function renderPipelineStepper(pipeline) {
    if (!pipelineStepper || !pipeline) return;

    const icons = {
      readiness: '📋',
      implementation: '⚙️',
      checks: '🧪',
      review: '👥',
      audit: '🛡️',
      pr_merge: '🚀'
    };

    pipelineStepper.innerHTML = pipeline.map((phase, idx) => {
      const stepClass = phase.status; // passed, running, failed, blocked, waiting, not_started
      return `
        <div class="step-item ${stepClass}">
          <div class="step-bubble" title="${escapeHtml(phase.summary)}">${icons[phase.name] || (idx + 1)}</div>
          <div class="step-label">${escapeHtml(phase.display_name)}</div>
        </div>
      `;
    }).join('');
  }

  function renderOverviewTab(detail) {
    const metaGrid = document.getElementById('overviewMetaGrid');
    const blockerSection = document.getElementById('overviewBlockerSection');
    const blockersList = document.getElementById('overviewBlockersList');

    if (metaGrid) {
      metaGrid.innerHTML = `
        <div class="meta-box">
          <div class="meta-box-label">Current Stage</div>
          <div class="meta-box-val">${escapeHtml(detail.current_stage || 'DISCOVERED')}</div>
        </div>
        <div class="meta-box">
          <div class="meta-box-label">Stop Outcome</div>
          <div class="meta-box-val">${escapeHtml(detail.stop_outcome || 'NONE')}</div>
        </div>
        <div class="meta-box">
          <div class="meta-box-label">Run ID</div>
          <div class="meta-box-val font-mono text-muted">${escapeHtml(detail.run_id || '---')}</div>
        </div>
        <div class="meta-box">
          <div class="meta-box-label">Active Job ID</div>
          <div class="meta-box-val font-mono text-muted">${escapeHtml(detail.job_id || '---')}</div>
        </div>
      `;
    }

    if (detail.blocker_details && detail.blocker_details.length > 0) {
      blockerSection.style.display = 'block';
      blockersList.innerHTML = detail.blocker_details.map(b => `
        <div class="attention-item-card">
          <div class="attention-item-left">
            <span class="attention-item-name">${escapeHtml(b.type || b.claim_type || 'BLOCKER')}</span>
            <span class="attention-item-reason">${escapeHtml(b.reason || b.description || '')}</span>
          </div>
          ${b.human_gate ? `<span class="badge badge-needs-human">${escapeHtml(b.human_gate)}</span>` : ''}
        </div>
      `).join('');
    } else {
      blockerSection.style.display = 'none';
    }
  }

  function renderCandidateTab(detail) {
    const summary = document.getElementById('candidateAuthSummary');
    const tbody = document.getElementById('candidateHistoryTbody');

    if (summary) {
      if (detail.candidate_authority) {
        const ca = detail.candidate_authority;
        summary.innerHTML = `
          <div class="overview-meta-grid">
            <div class="meta-box">
              <div class="meta-box-label">Current Candidate SHA</div>
              <div class="meta-box-val"><code class="code-sha">${escapeHtml(ca.candidate_sha)}</code></div>
            </div>
            <div class="meta-box">
              <div class="meta-box-label">Base SHA</div>
              <div class="meta-box-val"><code class="code-sha">${escapeHtml(ca.base_sha)}</code></div>
            </div>
            <div class="meta-box">
              <div class="meta-box-label">Generation</div>
              <div class="meta-box-val">Generation ${ca.generation} ${ca.is_frozen ? '(Frozen)' : '(Active)'}</div>
            </div>
            <div class="meta-box">
              <div class="meta-box-label">Manifest Hash</div>
              <div class="meta-box-val font-mono text-muted">${escapeHtml(ca.manifest_hash || '---')}</div>
            </div>
          </div>
          ${ca.changed_files && ca.changed_files.length > 0 ? `
            <div style="margin-top: 12px;">
              <div class="meta-box-label" style="margin-bottom: 4px;">Changed Files (${ca.changed_files.length})</div>
              <ul style="padding-left: 20px; font-family: var(--font-mono); font-size: 11px; color: var(--text-muted);">
                ${ca.changed_files.map(f => `<li>${escapeHtml(f)}</li>`).join('')}
              </ul>
            </div>
          ` : ''}
        `;
      } else {
        summary.innerHTML = `<p class="text-muted">No candidate generation finalized yet.</p>`;
      }
    }

    if (tbody) {
      if (detail.candidate_history && detail.candidate_history.length > 0) {
        tbody.innerHTML = detail.candidate_history.map(c => `
          <tr>
            <td><strong>gen-${c.generation}</strong></td>
            <td><code class="code-sha">${escapeHtml(c.candidate_sha_short)}</code></td>
            <td><code class="code-sha">${escapeHtml(c.base_sha_short)}</code></td>
            <td>${c.is_superseded ? '<span class="badge badge-not-ready">SUPERSEDED</span>' : '<span class="badge badge-ready">CURRENT</span>'}</td>
            <td class="font-mono text-muted">${escapeHtml(c.manifest_hash ? c.manifest_hash.substring(0, 10) + '...' : '---')}</td>
          </tr>
        `).join('');
      } else {
        tbody.innerHTML = `<tr><td colspan="5" class="table-empty">No candidate history.</td></tr>`;
      }
    }
  }

  function renderChecksTab(checks) {
    const countSpan = document.getElementById('checksTabCount');
    const container = document.getElementById('checksListContainer');
    if (countSpan) countSpan.textContent = checks ? checks.length : 0;

    if (!container) return;
    if (!checks || checks.length === 0) {
      container.innerHTML = `<p class="text-muted">No deterministic check results recorded.</p>`;
      return;
    }

    container.innerHTML = checks.map(c => {
      const isPass = c.status === 'PASS' || c.exit_code === 0;
      return `
        <div class="check-item">
          <div class="check-item-left">
            <div class="check-item-title">${escapeHtml(c.check_name)}</div>
            <div class="check-item-cmd">${escapeHtml(c.command)}</div>
            ${c.diagnostic_snippet ? `<div style="font-size: 11px; color: var(--color-danger); margin-top: 4px;">${escapeHtml(c.diagnostic_snippet)}</div>` : ''}
          </div>
          <div class="check-item-meta">
            <span class="text-muted" style="font-size: 11px;">${c.duration_ms ? `${c.duration_ms}ms` : ''}</span>
            <span class="badge ${isPass ? 'badge-ready' : 'badge-failed'}">${isPass ? 'PASS' : 'FAIL'}</span>
          </div>
        </div>
      `;
    }).join('');
  }

  function renderReviewTab(review) {
    const container = document.getElementById('reviewContentContainer');
    if (!container) return;

    if (!review || review.status === 'not_started') {
      container.innerHTML = `<p class="text-muted">Complementary review has not executed yet.</p>`;
      return;
    }

    const isPass = review.verdict === 'READY_TO_MERGE';
    container.innerHTML = `
      <div class="overview-meta-grid" style="margin-bottom: 12px;">
        <div class="meta-box">
          <div class="meta-box-label">Reviewer Role</div>
          <div class="meta-box-val">${escapeHtml(review.reviewer_role || 'antigravity')}</div>
        </div>
        <div class="meta-box">
          <div class="meta-box-label">Verdict</div>
          <div class="meta-box-val"><span class="badge ${isPass ? 'badge-ready' : 'badge-failed'}">${escapeHtml(review.verdict || review.status)}</span></div>
        </div>
        <div class="meta-box">
          <div class="meta-box-label">Material Findings</div>
          <div class="meta-box-val">${review.material_findings_count}</div>
        </div>
        <div class="meta-box">
          <div class="meta-box-label">Candidate Binding</div>
          <div class="meta-box-val"><code class="code-sha">${escapeHtml(review.candidate_sha ? review.candidate_sha.substring(0, 8) : '---')}</code> ${review.is_stale_to_current_candidate ? '<span class="badge badge-warning">STALE</span>' : ''}</div>
        </div>
      </div>
      ${review.summary ? `
        <div class="meta-box" style="margin-bottom: 12px;">
          <div class="meta-box-label">Review Summary</div>
          <p style="margin-top: 4px; font-size: 12px;">${escapeHtml(review.summary)}</p>
        </div>
      ` : ''}
      ${review.findings && review.findings.length > 0 ? `
        <div class="meta-box-label" style="margin-bottom: 6px;">Findings (${review.findings.length})</div>
        <div class="checks-list">
          ${review.findings.map(f => `
            <div class="check-item">
              <div class="check-item-left">
                <div class="check-item-title">${escapeHtml(f.severity)}: ${escapeHtml(f.location || 'Codebase')}</div>
                <div style="font-size: 11px; color: var(--text-muted);">${escapeHtml(f.violated_requirement || f.expected_correction || '')}</div>
              </div>
              <span class="badge ${f.severity === 'BLOCKER' ? 'badge-failed' : 'badge-waiting'}">${escapeHtml(f.severity)}</span>
            </div>
          `).join('')}
        </div>
      ` : '<p class="text-muted" style="font-size: 12px;">No findings reported.</p>'}
    `;
  }

  function renderAuditTab(audit) {
    const container = document.getElementById('auditContentContainer');
    if (!container) return;

    if (!audit || audit.status === 'not_started') {
      container.innerHTML = `<p class="text-muted">DeepSeek Direct audit has not executed yet.</p>`;
      return;
    }

    const isLowRisk = audit.risk === 'low' || audit.risk === null;
    container.innerHTML = `
      <div class="overview-meta-grid" style="margin-bottom: 12px;">
        <div class="meta-box">
          <div class="meta-box-label">Auditor</div>
          <div class="meta-box-val">${escapeHtml(audit.provider || 'deepseek')} / ${escapeHtml(audit.model || 'deepseek-chat')}</div>
        </div>
        <div class="meta-box">
          <div class="meta-box-label">Risk Level</div>
          <div class="meta-box-val"><span class="badge ${isLowRisk ? 'badge-ready' : 'badge-failed'}">RISK: ${escapeHtml(audit.risk || 'NONE')}</span></div>
        </div>
        <div class="meta-box">
          <div class="meta-box-label">Material Findings</div>
          <div class="meta-box-val">${audit.material_findings_count}</div>
        </div>
        <div class="meta-box">
          <div class="meta-box-label">Candidate Binding</div>
          <div class="meta-box-val"><code class="code-sha">${escapeHtml(audit.candidate_sha ? audit.candidate_sha.substring(0, 8) : '---')}</code> ${audit.is_stale_to_current_candidate ? '<span class="badge badge-warning">STALE</span>' : ''}</div>
        </div>
      </div>
      ${audit.summary ? `
        <div class="meta-box" style="margin-bottom: 12px;">
          <div class="meta-box-label">Audit Summary</div>
          <p style="margin-top: 4px; font-size: 12px;">${escapeHtml(audit.summary)}</p>
        </div>
      ` : ''}
      ${audit.findings && audit.findings.length > 0 ? `
        <div class="meta-box-label" style="margin-bottom: 6px;">Audit Findings (${audit.findings.length})</div>
        <div class="checks-list">
          ${audit.findings.map(f => `
            <div class="check-item">
              <div class="check-item-left">
                <div class="check-item-title">${escapeHtml(f.severity.toUpperCase())}: ${escapeHtml(f.category || 'General')}</div>
                <div style="font-size: 11px; color: var(--text-muted);">${escapeHtml(f.message || '')}</div>
              </div>
              <span class="badge ${f.severity === 'critical' || f.severity === 'high' ? 'badge-failed' : 'badge-waiting'}">${escapeHtml(f.severity.toUpperCase())}</span>
            </div>
          `).join('')}
        </div>
      ` : '<p class="text-muted" style="font-size: 12px;">No security or integrity findings reported.</p>'}
    `;
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
    const candSha = detail.candidate_authority ? detail.candidate_authority.candidate_sha : '';
    const baseSha = detail.candidate_authority ? detail.candidate_authority.base_sha : '';

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
        launchBtn.onclick = async () => {
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
                head_sha: candSha || 'HEAD',
                base_sha: baseSha || 'main',
                candidate_generation: detail.candidate_authority ? detail.candidate_authority.generation : 1,
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
      container.innerHTML = `<p class="text-muted">No GitHub Issue or Pull Request bound to this change.</p>`;
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
      container.innerHTML = `<p class="text-muted">No lifecycle events recorded for this change.</p>`;
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
    mainNavTabs.forEach((tab) => {
      const isTarget = tab.getAttribute('data-main-view') === viewName;
      tab.classList.toggle('active', isTarget);
      tab.setAttribute('aria-selected', isTarget ? 'true' : 'false');
    });

    mainViewPanes.forEach((pane) => {
      if (pane.id === viewName) {
        pane.style.display = 'block';
        pane.classList.add('active');
      } else {
        pane.style.display = 'none';
        pane.classList.remove('active');
      }
    });

    if (viewName === 'viewBacklog') {
      fetchBacklog(currentProjectId);
    } else if (viewName === 'viewProjects') {
      fetchProjects();
    } else if (viewName === 'viewExecutions') {
      fetchOverview();
    }
  }

  // Projects Operations
  async function fetchProjects() {
    try {
      const resp = await fetch('/api/v1/projects');
      if (resp.status === 401) {
        showLoginUI();
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
    const currentVal = projectSelect.value || currentProjectId || 'mini-me';
    projectSelect.innerHTML = projectsList.map((p) => `
      <option value="${escapeHtml(p.id)}" ${p.id === currentVal ? 'selected' : ''}>${escapeHtml(p.name || p.id)}</option>
    `).join('');
    if (projectsList.length > 0 && !projectsList.some(p => p.id === currentVal)) {
      currentProjectId = projectsList[0].id;
      projectSelect.value = currentProjectId;
    } else {
      currentProjectId = currentVal;
    }
    if (backlogProjectDisplay) {
      backlogProjectDisplay.textContent = `Project: ${currentProjectId}`;
    }
  }

  function renderProjectsGrid() {
    if (!projectsGridContainer) return;
    if (!projectsList || projectsList.length === 0) {
      projectsGridContainer.innerHTML = '<p class="text-muted">No projects registered yet. Click "Onboard Project" to bind your first repository.</p>';
      return;
    }

    projectsGridContainer.innerHTML = projectsList.map((p) => {
      const statusBadge = getProjectStatusBadge(p.onboarding_status);
      const isCurrent = p.id === currentProjectId;
      return `
        <div class="project-card ${isCurrent ? 'active-project-card' : ''}">
          <div class="project-card-header">
            <div class="project-card-title-group">
              <h3 class="project-name">${escapeHtml(p.name || p.id)}</h3>
              <span class="project-id font-mono text-muted text-xs">ID: ${escapeHtml(p.id)}</span>
            </div>
            ${statusBadge}
          </div>
          <div class="project-card-meta">
            <div class="meta-row"><strong>Repository:</strong> <span class="font-mono">${escapeHtml(p.repository)}</span></div>
            <div class="meta-row"><strong>Base Branch:</strong> <span class="font-mono">${escapeHtml(p.base_branch || 'main')}</span></div>
            <div class="meta-row"><strong>OpenSpec Path:</strong> <span class="font-mono">${escapeHtml(p.openspec_path || 'openspec')}</span></div>
            <div class="meta-row"><strong>Roadmap:</strong> <span class="font-mono">${escapeHtml(p.roadmap_path || 'docs/ROADMAP.md')}</span></div>
          </div>
          <div class="project-card-actions">
            <button class="btn btn-secondary btn-sm" onclick="window.minime.inspectContext('${escapeHtml(p.id)}')">
              🔍 Inspect Context
            </button>
            <button class="btn btn-secondary btn-sm" onclick="window.minime.discoverContext('${escapeHtml(p.id)}')">
              🔄 Discover
            </button>
            <button class="btn btn-primary btn-sm" onclick="window.minime.selectProjectAndGoBacklog('${escapeHtml(p.id)}')">
              📥 Open Backlog
            </button>
          </div>
        </div>
      `;
    }).join('');
  }

  function getProjectStatusBadge(status) {
    switch (status) {
      case 'READY_FOR_WORK': return '<span class="badge badge-ready">READY FOR WORK</span>';
      case 'CONTEXT_INCOMPLETE': return '<span class="badge badge-waiting">CONTEXT INCOMPLETE</span>';
      case 'BINDING': return '<span class="badge badge-running">BINDING</span>';
      case 'BLOCKED': return '<span class="badge badge-failed">BLOCKED</span>';
      default: return '<span class="badge badge-not-ready">UNBOUND</span>';
    }
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
    try {
      const resp = await fetch(`/api/v1/projects/${encodeURIComponent(projectId)}/backlog`);
      if (resp.status === 401) {
        showLoginUI();
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

  function renderBacklogTable() {
    if (!backlogTableBody) return;

    let filtered = backlogItems;
    if (backlogFilter !== 'ALL') {
      filtered = filtered.filter(i => {
        if (backlogFilter === 'NEEDS_HUMAN') return i.status === 'NEEDS_HUMAN';
        if (backlogFilter === 'READY') return i.status === 'READY';
        if (backlogFilter === 'RUNNING') return i.status === 'RUNNING';
        if (backlogFilter === 'COMPLETED') return i.status === 'COMPLETED';
        if (backlogFilter === 'BACKLOG') return i.status === 'BACKLOG' || i.status === 'DRAFT' || i.status === 'PREPARING';
        return true;
      });
    }

    if (backlogSearchQuery) {
      filtered = filtered.filter(i =>
        i.title.toLowerCase().includes(backlogSearchQuery) ||
        i.item_key.toLowerCase().includes(backlogSearchQuery) ||
        (i.description && i.description.toLowerCase().includes(backlogSearchQuery))
      );
    }

    if (!filtered || filtered.length === 0) {
      backlogTableBody.innerHTML = `
        <tr><td colspan="6" class="table-empty">No backlog items matching current filter.</td></tr>
      `;
      return;
    }

    backlogTableBody.innerHTML = filtered.map(item => {
      const isSelected = selectedBacklogItem && selectedBacklogItem.item_key === item.item_key;
      const statusClass = getStatusBadgeClass(item.status);
      const priorityClass = getPriorityBadgeClass(item.priority);
      const isReady = item.status === 'READY';

      return `
        <tr class="clickable-row ${isSelected ? 'selected-row' : ''}" data-item-key="${escapeHtml(item.item_key)}">
          <td><span class="badge ${statusClass}">${escapeHtml(item.status)}</span></td>
          <td>
            <div class="bk-title font-semibold">${escapeHtml(item.title)}</div>
            <div class="bk-key font-mono text-muted text-xs">${escapeHtml(item.item_key)}</div>
          </td>
          <td><span class="badge ${priorityClass}">${escapeHtml(item.priority || 'NORMAL')}</span></td>
          <td><span class="badge badge-discovered">${escapeHtml(item.source || 'MANUAL')}</span></td>
          <td>
            <span class="dor-status-pill ${isReady ? 'pill-ready' : (item.status === 'NEEDS_HUMAN' ? 'pill-needs-human' : 'pill-not-ready')}">
              ${isReady ? 'READY' : (item.status === 'NEEDS_HUMAN' ? 'NEEDS HUMAN' : 'NOT READY')}
            </span>
          </td>
          <td>
            <div class="action-btn-group">
              ${!isReady && item.status !== 'RUNNING' && item.status !== 'COMPLETED' ? `
                <button class="btn btn-secondary btn-xs" onclick="event.stopPropagation(); window.minime.prepareItem('${escapeHtml(item.item_key)}')">Prepare</button>
              ` : ''}
              ${isReady ? `
                <button class="btn btn-primary btn-xs" onclick="event.stopPropagation(); window.minime.startItem('${escapeHtml(item.item_key)}')">🚀 Start</button>
              ` : ''}
            </div>
          </td>
        </tr>
      `;
    }).join('');
  }

  function getPriorityBadgeClass(priority) {
    switch (priority) {
      case 'CRITICAL': return 'badge-danger';
      case 'HIGH': return 'badge-warning';
      case 'LOW': return 'badge-muted';
      default: return 'badge-info';
    }
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
    if (!item) {
      if (backlogPlaceholder) backlogPlaceholder.style.display = 'flex';
      if (backlogDetailContent) backlogDetailContent.style.display = 'none';
      return;
    }

    if (backlogPlaceholder) backlogPlaceholder.style.display = 'none';
    if (backlogDetailContent) backlogDetailContent.style.display = 'block';

    if (bkTitle) bkTitle.textContent = item.title;
    if (bkStatusBadge) {
      bkStatusBadge.textContent = item.status;
      bkStatusBadge.className = `badge ${getStatusBadgeClass(item.status)}`;
    }
    if (bkPriorityBadge) {
      bkPriorityBadge.textContent = item.priority || 'NORMAL';
      bkPriorityBadge.className = `badge ${getPriorityBadgeClass(item.priority)}`;
    }
    if (bkKey) bkKey.textContent = item.item_key;
    if (bkSource) bkSource.textContent = item.source || 'MANUAL';
    if (bkReadiness) bkReadiness.textContent = item.status === 'READY' ? 'READY' : (item.status === 'NEEDS_HUMAN' ? 'NEEDS_HUMAN' : 'NOT_READY');

    // Action button state
    if (bkStartBtn) {
      bkStartBtn.disabled = item.status !== 'READY';
      if (item.status === 'RUNNING') {
        bkStartBtn.textContent = '⚡ Running...';
      } else {
        bkStartBtn.innerHTML = '<span class="btn-icon">🚀</span> Start Work';
      }
    }

    // NEEDS_HUMAN Card
    if (bkNeedsHumanCard) {
      const hasQuestions = (item.status === 'NEEDS_HUMAN') || (item.human_questions && item.human_questions.length > 0);
      if (hasQuestions) {
        bkNeedsHumanCard.style.display = 'block';
        if (bkHumanQuestionsList) {
          const questions = item.human_questions && item.human_questions.length > 0
            ? item.human_questions
            : ['Please provide more functional details and observable acceptance criteria.'];
          bkHumanQuestionsList.innerHTML = questions.map(q => `
            <div class="question-item">
              <span class="question-icon">❓</span>
              <span class="question-text">${escapeHtml(q)}</span>
            </div>
          `).join('');
        }
      } else {
        bkNeedsHumanCard.style.display = 'none';
      }
    }

    // Description & Criteria
    if (bkDescriptionPreview) {
      bkDescriptionPreview.innerHTML = renderMarkdownText(item.description || 'No description provided.');
    }
    if (bkCriteriaList) {
      if (item.acceptance_criteria && item.acceptance_criteria.length > 0) {
        bkCriteriaList.innerHTML = item.acceptance_criteria.map(c => `
          <li class="criteria-item">✓ ${escapeHtml(c)}</li>
        `).join('');
      } else {
        bkCriteriaList.innerHTML = '<li class="text-muted">No explicit acceptance criteria specified.</li>';
      }
    }

    // DoR Checklist (11 criteria)
    renderDoRChecklist(item);

    // Canonical Artifacts
    if (bkArtOpenSpec) {
      bkArtOpenSpec.innerHTML = item.openspec_change_name
        ? `<span class="text-success font-mono">openspec/changes/${escapeHtml(item.openspec_change_name)}</span>`
        : '<span class="text-muted">Not generated yet</span>';
    }
    if (bkArtIssue) {
      bkArtIssue.innerHTML = item.github_issue_url
        ? `<a href="${sanitizeUrl(item.github_issue_url)}" target="_blank" rel="noopener noreferrer" class="text-primary font-mono">#${item.github_issue_number} ↗</a>`
        : (item.github_issue_number ? `#${item.github_issue_number}` : '<span class="text-muted">Not linked yet</span>');
    }
    if (bkArtProject) {
      bkArtProject.innerHTML = item.github_project_item_id
        ? `<span class="text-success font-mono">${escapeHtml(item.github_project_item_id)}</span>`
        : '<span class="text-muted">Not synced yet</span>';
    }
    if (bkArtRun) {
      bkArtRun.innerHTML = item.active_orchestration_run_id
        ? `<span class="text-primary font-mono" style="cursor:pointer;" onclick="window.minime.goToExecution('${escapeHtml(item.active_orchestration_run_id)}')">${escapeHtml(item.active_orchestration_run_id)} ↗</span>`
        : '<span class="text-muted">No active run</span>';
    }
  }

  function renderDoRChecklist(item) {
    if (!bkDorGrid) return;
    const checklist = item.readiness_checklist || {};
    const isReady = item.status === 'READY' || checklist.is_ready;

    if (bkDorOverallPill) {
      bkDorOverallPill.textContent = isReady ? 'READY FOR ADMISSION' : (item.status === 'NEEDS_HUMAN' ? 'NEEDS HUMAN' : 'NOT READY');
      bkDorOverallPill.className = `dor-status-pill ${isReady ? 'pill-ready' : (item.status === 'NEEDS_HUMAN' ? 'pill-needs-human' : 'pill-not-ready')}`;
    }

    const dorRules = [
      { key: 'repo_binding_valid', label: 'Repository Binding Valid', val: checklist.repo_binding_valid ?? !!item.project_id },
      { key: 'item_identity_valid', label: 'Work Item Identity Valid', val: checklist.item_identity_valid ?? !!(item.item_key && item.title) },
      { key: 'github_issue_linked', label: 'GitHub Issue Linked', val: checklist.github_issue_linked ?? !!item.github_issue_number },
      { key: 'github_project_linked', label: 'GitHub Project Item Linked', val: checklist.github_project_linked ?? !!item.github_project_item_id },
      { key: 'openspec_valid', label: 'OpenSpec Artifacts Generated', val: checklist.openspec_valid ?? !!item.openspec_change_name },
      { key: 'acceptance_criteria_present', label: 'Acceptance Criteria Defined', val: checklist.acceptance_criteria_present ?? (item.acceptance_criteria && item.acceptance_criteria.length > 0) },
      { key: 'dependencies_resolved', label: 'Dependencies Resolved', val: checklist.dependencies_resolved ?? true },
      { key: 'security_requirements_identified', label: 'Security Requirements Identified', val: checklist.security_requirements_identified ?? true },
      { key: 'ux_requirements_identified', label: 'UX / Preview Identified', val: checklist.ux_requirements_identified ?? true },
      { key: 'no_unresolved_ambiguity', label: 'No Unresolved Ambiguity', val: checklist.no_unresolved_ambiguity ?? (item.status !== 'NEEDS_HUMAN') },
      { key: 'definition_of_ready_met', label: 'Definition of Ready Met', val: isReady }
    ];

    bkDorGrid.innerHTML = dorRules.map(r => `
      <div class="dor-item ${r.val ? 'dor-pass' : 'dor-fail'}">
        <span class="dor-icon">${r.val ? '✓' : '✗'}</span>
        <span class="dor-label">${escapeHtml(r.label)}</span>
      </div>
    `).join('');
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
  window.minime = {
    inspectContext,
    discoverContext: (projId) => discoverBacklogContext(projId),
    selectProjectAndGoBacklog: (projId) => {
      currentProjectId = projId;
      if (projectSelect) projectSelect.value = projId;
      switchMainView('viewBacklog');
    },
    prepareItem: (itemKey) => prepareBacklogItem(itemKey),
    startItem: (itemKey) => startBacklogItem(itemKey),
    goToExecution: (runId) => {
      switchMainView('viewExecutions');
    }
  };

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
      if (diffSec < 60) return `${diffSec}s ago`;
      if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
      if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
      return `${Math.floor(diffSec / 86400)}d ago`;
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

  // Start Application
  document.addEventListener('DOMContentLoaded', init);
})();
