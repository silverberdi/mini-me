import { renderProviders } from "../components/provider_grid.js";
import { renderQueue } from "../components/queue_table.js";

function latestTimestamp(records, fields) {
  if (!Array.isArray(records)) return null;
  const timestamps = records
    .flatMap((record) => fields.map((field) => record?.[field]))
    .filter((value) => typeof value === "string" && !Number.isNaN(Date.parse(value)));
  return timestamps.sort((left, right) => Date.parse(right) - Date.parse(left))[0] || null;
}

function updateFreshness(node, result, sourceTime, formatRelativeTime) {
  if (!node) return;
  if (result.status !== "fulfilled") {
    node.textContent = "No disponible";
    node.dataset.state = "UNKNOWN";
    return;
  }
  if (!sourceTime || Number.isNaN(Date.parse(sourceTime))) {
    node.textContent = "Antigüedad desconocida: la fuente no informa hora de observación";
    node.dataset.state = "UNKNOWN";
    return;
  }
  node.textContent = `Observado ${formatRelativeTime(sourceTime)}`;
  node.dataset.state = "OBSERVED";
}

export function renderOperationalPanels({ data, results, elements, selectChange, formatRelativeTime }) {
  renderQueue(elements.queueList, data.queue, (projectId, changeName) => selectChange(projectId, changeName));
  renderProviders(elements.providerGrid, data.providers);
  updateFreshness(elements.overviewFreshness, results.overview, data.overview?.observed_at, formatRelativeTime);
  updateFreshness(
    elements.queueFreshness,
    results.queue,
    latestTimestamp(data.queue, ["last_evaluated_at"]),
    formatRelativeTime,
  );
  updateFreshness(
    elements.providerFreshness,
    results.providers,
    latestTimestamp(data.providers, ["last_probe_at", "updated_at"]),
    formatRelativeTime,
  );
  updateFreshness(elements.healthFreshness, results.health, data.health?.observed_at, formatRelativeTime);
  updateFreshness(
    elements.activityFreshness,
    results.activity,
    latestTimestamp(data.activity, ["timestamp"]),
    formatRelativeTime,
  );
  renderActivity(elements.activityList, data.activity, results.activity);

  const healthy = data.health?.database?.healthy;
  if (elements.dbHealthBadge) {
    elements.dbHealthBadge.textContent = healthy === true
      ? "Base de datos disponible"
      : healthy === false ? "Base de datos no disponible" : "Estado de base de datos desconocido";
    elements.dbHealthBadge.dataset.state = healthy === true ? "HEALTHY" : healthy === false ? "UNHEALTHY" : "UNKNOWN";
  }
  if (elements.kpiSystemStateVal) {
    elements.kpiSystemStateVal.textContent = healthy === true
      ? "Saludable" : healthy === false ? "Degradado" : "Desconocido";
    elements.kpiSystemStateVal.className = `kpi-value ${healthy === true ? "text-success" : healthy === false ? "text-danger" : "text-muted"}`;
  }
}

function renderActivity(root, events, result) {
  if (!root) return;
  if (result?.status !== "fulfilled" || !Array.isArray(events)) {
    root.innerHTML = '<li class="table-empty" data-state="UNKNOWN">Actividad no disponible; no se conserva una lectura anterior como actual.</li>';
    return;
  }
  if (!events.length) {
    root.innerHTML = '<li class="table-empty">El servidor no informó eventos recientes.</li>';
    return;
  }
  root.innerHTML = events.map((event) => `<li class="activity-item">
    <time datetime="${escapeHtml(event.timestamp)}">${escapeHtml(event.timestamp)}</time>
    <span class="activity-event">${escapeHtml(event.event_type)}</span>
    <span class="activity-summary">${escapeHtml(event.summary)}</span>
    <span class="activity-actor">${escapeHtml(event.actor || "system")}</span>
  </li>`).join("");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

export function updateSchedulerServiceObservation(node, systemStatus) {
  const observation = systemStatus?.scheduler_service;
  if (!node) return;
  const fresh = observation?.freshness === "FRESH";
  const active = fresh ? observation.active_state : "UNKNOWN";
  const enabled = fresh ? observation.enabled_state : "UNKNOWN";
  const sub = fresh ? observation.sub_state : "UNKNOWN";
  node.textContent = `Servicio: ${active}${sub !== "UNKNOWN" ? ` (${sub})` : ""} · Arranque: ${enabled}`;
  node.dataset.state = fresh ? active : "UNKNOWN";
  node.title = fresh && observation.observed_at
    ? `Origen: ${observation.source}; observado: ${observation.observed_at}; antigüedad: ${observation.age_seconds ?? "desconocida"} s`
    : `Observación systemd no disponible: ${observation?.reason || "UNKNOWN"}`;
}
