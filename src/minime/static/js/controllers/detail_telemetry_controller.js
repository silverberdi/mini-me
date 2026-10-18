import { actionHistory } from '../services/control_plane_client.js';
import { renderActionHistory, renderEfficiencyTelemetry } from '../views/detail_telemetry_views.js';

/** Loads candidate-independent telemetry for the currently selected Run/Change. */
export function createDetailTelemetryController({
  fetchRequest,
  loadActionHistory = actionHistory,
  efficiencyContainer,
  historyContainer,
  formatTimestamp,
}) {
  let selectionSequence = 0;

  function showUnavailable(sequence, container, message) {
    if (sequence === selectionSequence && container) {
      container.innerHTML = `<p class="table-empty">${message}</p>`;
    }
  }

  async function renderFor(detail) {
    const sequence = ++selectionSequence;
    const projectId = detail?.project_id;
    const changeName = detail?.change_name;
    const runId = detail?.run_id;
    if (!projectId || !changeName) {
      renderEfficiencyTelemetry(efficiencyContainer, null, formatTimestamp);
      renderActionHistory(historyContainer, [], formatTimestamp);
      return;
    }

    const efficiencyRequest = fetchRequest(
      `/api/v1/efficiency/${encodeURIComponent(projectId)}/${encodeURIComponent(changeName)}`,
    ).then(async (response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    });
    const historyRequest = runId
      ? loadActionHistory(runId)
      : Promise.resolve([]);

    const [efficiency, history] = await Promise.allSettled([efficiencyRequest, historyRequest]);
    if (sequence !== selectionSequence) return;
    if (efficiency.status === 'fulfilled') {
      renderEfficiencyTelemetry(efficiencyContainer, efficiency.value, formatTimestamp);
    } else {
      showUnavailable(sequence, efficiencyContainer, 'No se pudo cargar la telemetría de eficiencia.');
    }
    if (history.status === 'fulfilled') {
      renderActionHistory(historyContainer, history.value, formatTimestamp);
    } else {
      showUnavailable(sequence, historyContainer, 'No se pudo cargar la trazabilidad de acciones.');
    }
  }

  return { renderFor };
}
