import { renderKpis } from "../components/kpi_grid.js";

export function renderOverviewView({ data, elements, escapeHtml, updateSchedulerServiceObservation, renderChanges }) {
  if (!data) {
    renderKpis(elements.kpiGrid, {});
    updateSchedulerServiceObservation(elements.schedulerServiceBadge, null);
    if (elements.kpiSystemStateVal) elements.kpiSystemStateVal.textContent = "—";
    if (elements.attentionItemsContainer) elements.attentionItemsContainer.replaceChildren();
    if (elements.attentionBanner) elements.attentionBanner.style.display = "none";
    if (elements.changesTableBody) {
      elements.changesTableBody.innerHTML = '<tr><td colspan="6" class="table-empty">Datos operacionales no disponibles; se requiere una lectura autenticada reciente.</td></tr>';
    }
    if (elements.detailContent) elements.detailContent.style.display = "none";
    if (elements.detailPlaceholder) {
      elements.detailPlaceholder.style.display = "block";
      elements.detailPlaceholder.textContent = "Detalle no disponible hasta recuperar una lectura autenticada reciente.";
    }
    return;
  }

  const { system_status: status, attention_items: attentionItems = [] } = data;
  renderKpis(elements.kpiGrid, status);
  if (elements.schedulerModeBadge) {
    const mode = status.scheduler_mode || "UNKNOWN";
    elements.schedulerModeBadge.textContent = `Admisión lógica: ${mode}`;
    elements.schedulerModeBadge.dataset.state = mode;
  }
  updateSchedulerServiceObservation(elements.schedulerServiceBadge, status);

  if (elements.kpiSystemStateSub) {
    elements.kpiSystemStateSub.textContent = `API/PostgreSQL · admisión: ${status.scheduler_mode || "UNKNOWN"}`;
  }
  if (elements.kpiAttentionSub) {
    const count = status.attention_runs_count;
    elements.kpiAttentionSub.textContent = Number.isInteger(count)
      ? `${count} ejecución${count === 1 ? "" : "es"} requiere${count === 1 ? "" : "n"} atención`
      : "Cantidad de atención no disponible";
  }
  if (elements.kpiActiveSub) {
    const count = status.active_runs_count;
    elements.kpiActiveSub.textContent = Number.isInteger(count)
      ? `${count} ejecuciones activas informadas` : "Ejecuciones activas no disponibles";
  }
  if (elements.kpiCompletedSub) {
    elements.kpiCompletedSub.textContent = "Finalizaciones recientes informadas por el servidor";
  }

  if (attentionItems.length) {
    if (elements.attentionBanner) elements.attentionBanner.style.display = "block";
    if (elements.attentionCountText) {
      elements.attentionCountText.textContent = `${attentionItems.length} ejecución${attentionItems.length === 1 ? "" : "es"}`;
    }
    if (elements.attentionItemsContainer) {
      elements.attentionItemsContainer.innerHTML = attentionItems.map((item) => `
        <button type="button" class="attention-item-card" data-project-id="${escapeHtml(item.project_id)}" data-change-name="${escapeHtml(item.change_name)}" aria-label="Abrir ${escapeHtml(item.project_id)} / ${escapeHtml(item.change_name)}: ${escapeHtml(item.reason)}">
          <div class="attention-item-left">
            <span class="attention-item-name">${escapeHtml(item.project_id)} / ${escapeHtml(item.change_name)}</span>
            <span class="attention-item-reason">${escapeHtml(item.reason)}</span>
          </div>
          <span class="badge badge-needs-human">${escapeHtml(item.stop_outcome || item.stage)}</span>
        </button>
      `).join("");
    }
  } else if (elements.attentionBanner) {
    elements.attentionBanner.style.display = "none";
  }
  renderChanges();
}
