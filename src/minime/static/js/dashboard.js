/**
 * mini me — Operations Dashboard Application Logic
 */

(function () {
  'use strict';

  // State
  let overviewData = null;
  let selectedChange = null;
  let activeFilter = 'ALL';
  let searchQuery = '';
  let refreshIntervalSeconds = parseInt(localStorage.getItem('minime_dashboard_interval') || '10', 10);
  let countdownSeconds = refreshIntervalSeconds;
  let countdownInterval = null;

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

  // Initialization
  function init() {
    setupTheme();
    setupEventListeners();
    fetchOverview();
    setupAutoRefresh();
  }

  // Theme Handling
  function setupTheme() {
    const savedTheme = localStorage.getItem('minime_theme') || 'theme-dark';
    document.body.className = savedTheme;
    updateThemeIcon(savedTheme);
  }

  function toggleTheme() {
    const isDark = document.body.classList.contains('theme-dark');
    const newTheme = isDark ? 'theme-light' : 'theme-dark';
    document.body.className = newTheme;
    localStorage.setItem('minime_theme', newTheme);
    updateThemeIcon(newTheme);
  }

  function updateThemeIcon(theme) {
    if (themeIcon) {
      themeIcon.textContent = theme === 'theme-light' ? '🌙' : '☀️';
    }
  }

  // Event Listeners
  function setupEventListeners() {
    if (refreshBtn) {
      refreshBtn.addEventListener('click', () => {
        fetchOverview();
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
        localStorage.setItem('minime_dashboard_interval', String(refreshIntervalSeconds));
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
        <div class="attention-item-card" onclick="window.selectChange('${escapeHtml(item.project_id)}', '${escapeHtml(item.change_name)}')">
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
        <tr class="${isSelected ? 'selected' : ''}" onclick="window.selectChange('${escapeHtml(c.project_id)}', '${escapeHtml(c.change_name)}')">
          <td><span class="badge ${statusClass}">${escapeHtml(c.status)}</span></td>
          <td><strong>${escapeHtml(c.change_name)}</strong></td>
          <td>${escapeHtml(c.project_id)}</td>
          <td><span class="text-muted">${escapeHtml(c.stop_outcome || c.current_stage || '---')}</span></td>
          <td><code class="code-sha">${escapeHtml(shortSha)}</code></td>
          <td class="text-muted">${escapeHtml(updated)}</td>
        </tr>
      `;
    }).join('');

    // Auto-select first change if none selected
    if (!selectedChange && list.length > 0) {
      window.selectChange(list[0].project_id, list[0].change_name);
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

    // Tab 6: GitHub & PR
    renderGitHubTab(detail.github, detail.project_id);

    // Tab 7: Timeline
    renderTimelineTab(detail.timeline);
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
          <div class="meta-box-val">${github.issue_url ? `<a href="${escapeHtml(github.issue_url)}" target="_blank" class="text-primary">#${github.issue_number} ↗</a>` : (github.issue_number ? `#${github.issue_number}` : '---')}</div>
        </div>
        <div class="meta-box">
          <div class="meta-box-label">Pull Request</div>
          <div class="meta-box-val">${github.pr_url ? `<a href="${escapeHtml(github.pr_url)}" target="_blank" class="text-primary">PR #${github.pr_number} ↗</a>` : (github.pr_number ? `PR #${github.pr_number}` : 'None created yet')}</div>
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
