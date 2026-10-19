import { api } from "../services/api_client.js";
import { renderOperationalPanels as renderOperationalPanelsView, updateSchedulerServiceObservation } from "../views/operational_panels_view.js";
import { renderOverviewView } from "../views/overview_view.js";
import { renderChangesView } from "../views/runs_view.js";

/** Owns authenticated Control Center read state, Change selection and refresh reconciliation. */
export function createExecutionViewController({
  fetchRequest,
  readApi = api,
  elements,
  setOfflineBanner,
  onUnauthorized,
  getNavigationState,
  renderDetail,
  setDetailDrawerOpen = () => {},
  statusClass,
  formatRelativeTime,
}) {
  let overviewData = null;
  let queueData = null;
  let providerData = null;
  let healthData = null;
  let activityData = null;
  let selectedChange = null;
  let detailRequestSequence = 0;
  let refreshInProgress = false;
  let refreshPending = false;
  let initialSelected = false;

  function renderOperationalPanels(results) {
    renderOperationalPanelsView({
      data: { overview: overviewData, queue: queueData, providers: providerData, health: healthData, activity: activityData },
      results: {
        overview: results.overviewResult,
        queue: results.queueResult,
        providers: results.providerResult,
        health: results.healthResult,
        activity: results.activityResult,
      },
      elements: {
        queueList: elements.queueList,
        providerGrid: elements.providerGrid,
        overviewFreshness: elements.overviewFreshness,
        queueFreshness: elements.queueFreshness,
        providerFreshness: elements.providerFreshness,
        healthFreshness: elements.healthFreshness,
        activityFreshness: elements.activityFreshness,
        activityList: elements.activityList,
        dbHealthBadge: elements.dbHealthBadge,
        kpiSystemStateVal: elements.kpiSystemStateVal,
      },
      selectChange,
      formatRelativeTime,
    });
  }

  function renderChangesTable() {
    if (!overviewData?.changes) return;
    const navigation = getNavigationState();
    initialSelected = renderChangesView({
      root: elements.changesTableBody,
      changes: overviewData.changes,
      filter: navigation?.activeFilter || "ALL",
      query: navigation?.searchQuery || "",
      selected: selectedChange,
      alreadyAutoSelected: initialSelected,
      statusClass,
      formatTime: formatRelativeTime,
      onSelect: selectChange,
    });
  }

  function renderOverview() {
    if (!overviewData) setOfflineBanner(typeof navigator !== "undefined" && navigator.onLine === false);
    else setOfflineBanner(false);
    renderOverviewView({
      data: overviewData,
      elements: {
        kpiGrid: elements.kpiGrid,
        schedulerServiceBadge: elements.schedulerServiceBadge,
        schedulerModeBadge: elements.schedulerModeBadge,
        kpiSystemStateVal: elements.kpiSystemStateVal,
        kpiSystemStateSub: elements.kpiSystemStateSub,
        kpiAttentionVal: elements.kpiAttentionVal,
        kpiAttentionSub: elements.kpiAttentionSub,
        kpiActiveVal: elements.kpiActiveVal,
        kpiActiveSub: elements.kpiActiveSub,
        kpiCompletedVal: elements.kpiCompletedVal,
        kpiCompletedSub: elements.kpiCompletedSub,
        attentionBanner: elements.attentionBanner,
        attentionCountText: elements.attentionCountText,
        attentionItemsContainer: elements.attentionItemsContainer,
        changesTableBody: elements.changesTableBody,
        detailContent: elements.detailContent,
        detailPlaceholder: elements.detailPlaceholder,
      },
      escapeHtml,
      updateSchedulerServiceObservation,
      renderChanges: renderChangesTable,
    });
  }

  async function fetchChangeDetail(projectId, changeName) {
    const requestSequence = ++detailRequestSequence;
    try {
      const response = await fetchRequest(`/api/v1/dashboard/changes/${encodeURIComponent(projectId)}/${encodeURIComponent(changeName)}`);
      if ([401, 403].includes(response.status)) {
        onUnauthorized();
        return;
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const detail = await response.json();
      if (requestSequence !== detailRequestSequence
          || selectedChange?.project_id !== projectId
          || selectedChange?.change_name !== changeName) return;
      if (!isValidChangeDetail(detail, projectId, changeName)) {
        throw new Error("La lectura del detalle no cumple el contrato autenticado para la identidad seleccionada.");
      }
      renderDetail(detail);
    } catch (error) {
      if (requestSequence === detailRequestSequence) {
        console.error("No se pudo consultar el detalle del cambio:", error);
        if (elements.detailContent) elements.detailContent.style.display = "none";
        if (elements.detailPlaceholder) {
          elements.detailPlaceholder.style.display = "block";
          elements.detailPlaceholder.textContent = "Detalle no disponible; vuelve a actualizar cuando se recupere la conexión.";
        }
      }
    }
  }

  function selectChange(projectId, changeName, options = {}) {
    selectedChange = { project_id: projectId, change_name: changeName };
    setDetailDrawerOpen(options.openDrawer !== false, selectedChange);
    if (elements.detailContent) elements.detailContent.style.display = "none";
    if (elements.detailPlaceholder) {
      elements.detailPlaceholder.style.display = "block";
      elements.detailPlaceholder.textContent = "Cargando evidencia del cambio seleccionado…";
    }
    renderChangesTable();
    void fetchChangeDetail(projectId, changeName);
  }

  async function refreshOnce() {
    const [overviewResult, queueResult, providerResult, healthResult, activityResult] = await Promise.allSettled([
      readApi.overview(), readApi.queue(), readApi.providers(), readApi.health(), readApi.events(),
    ]);
    const safeOverviewResult = overviewResult.status === "fulfilled" && !isValidOverview(overviewResult.value)
      ? { status: "rejected", reason: new Error("La lectura general no cumple el contrato autenticado.") }
      : overviewResult;
    const unauthorized = [overviewResult, queueResult, providerResult, healthResult, activityResult]
      .some((result) => result.status === "rejected" && [401, 403].includes(result.reason?.status));
    if (unauthorized) {
      clear();
      onUnauthorized();
      renderOperationalPanels({ overviewResult, queueResult, providerResult, healthResult, activityResult });
      return;
    }
    overviewData = safeOverviewResult.status === "fulfilled" ? safeOverviewResult.value : null;
    queueData = queueResult.status === "fulfilled" ? queueResult.value : null;
    providerData = providerResult.status === "fulfilled" ? providerResult.value : null;
    healthData = healthResult.status === "fulfilled" ? healthResult.value : null;
    activityData = activityResult.status === "fulfilled" ? activityResult.value : null;
    renderOverview();
    renderOperationalPanels({ overviewResult: safeOverviewResult, queueResult, providerResult, healthResult, activityResult });
    if (selectedChange && overviewData) void fetchChangeDetail(selectedChange.project_id, selectedChange.change_name);
  }

  async function refresh() {
    if (refreshInProgress) {
      refreshPending = true;
      return;
    }
    refreshInProgress = true;
    try {
      do {
        refreshPending = false;
        await refreshOnce();
      } while (refreshPending);
    } finally {
      refreshInProgress = false;
    }
  }

  function clear() {
    overviewData = null;
    queueData = null;
    providerData = null;
    healthData = null;
    activityData = null;
    selectedChange = null;
    setDetailDrawerOpen(false);
    detailRequestSequence += 1;
    renderOverview();
    const rejected = { status: "rejected" };
    renderOperationalPanels({ overviewResult: rejected, queueResult: rejected, providerResult: rejected, healthResult: rejected, activityResult: rejected });
  }

  return {
    refresh,
    clear,
    renderChangesTable,
    selectChange,
    refreshSelectedDetail() {
      if (!selectedChange) return Promise.resolve();
      return fetchChangeDetail(selectedChange.project_id, selectedChange.change_name);
    },
    get selectedChange() { return selectedChange ? { ...selectedChange } : null; },
  };
}

function escapeHtml(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function isValidOverview(overview) {
  return Boolean(overview && typeof overview === "object" && !Array.isArray(overview)
    && overview.system_status && typeof overview.system_status === "object" && !Array.isArray(overview.system_status)
    && Array.isArray(overview.attention_items)
    && Array.isArray(overview.active_executions)
    && Array.isArray(overview.recent_completions)
    && Array.isArray(overview.changes));
}

function isValidChangeDetail(detail, projectId, changeName) {
  if (!detail || typeof detail !== "object" || Array.isArray(detail)) return false;
  if (detail.project_id !== projectId || detail.change_name !== changeName) return false;
  if (typeof detail.status !== "string" || !detail.status.length) return false;
  if (!(detail.run_id === null || typeof detail.run_id === "string")) return false;
  if (!(detail.job_id === null || typeof detail.job_id === "string")) return false;
  if (detail.run_id === null && detail.job_id !== null) return false;
  if (!Array.isArray(detail.pipeline) || !Array.isArray(detail.candidate_history)
      || !Array.isArray(detail.checks) || !Array.isArray(detail.timeline)
      || !Array.isArray(detail.blocker_details)) return false;
  if (!(detail.candidate_authority === null
      || (typeof detail.candidate_authority === "object" && !Array.isArray(detail.candidate_authority)))) {
    return false;
  }
  return ["review", "audit", "github", "preview_validation"].every((field) =>
    detail[field] !== null && typeof detail[field] === "object" && !Array.isArray(detail[field]));
}
