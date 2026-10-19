const escapeHtml = (value) => String(value ?? '').replace(/[&<>\"']/g, (character) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;', "'": '&#39;',
})[character]);

export function renderEfficiencyTelemetry(container, data, formatTimestamp) {
  if (!container) return;
  if (!data) {
    container.innerHTML = '<p class="table-empty">No hay telemetría registrada para este cambio.</p>';
    return;
  }
  const metrics = data.metrics || data;
  const ratio = data.productive_attempt_ratio !== undefined
    ? `${(Number(data.productive_attempt_ratio) * 100).toFixed(0)}%` : 'No informado';
  const attempts = data.total_attempts ?? 'No informado';
  const reworks = metrics.corrective_retry_count ?? data.rework_attempts ?? 'No informado';
  const model = data.primary_model || data.provider_summary?.[0]?.provider || 'No informado';
  const reviewerModel = data.reviewer_model || data.provider_summary?.[1]?.provider || 'No informado';
  const independence = data.reviewer_independence === true ? 'VERIFICADA'
    : data.reviewer_independence === false ? 'NO VERIFICADA' : 'DESCONOCIDA';
  const selfHost = metrics.self_hosting_percentage !== undefined
    ? `${metrics.self_hosting_percentage.toFixed(0)}%` : 'No informado';

  container.innerHTML = `
    <div class="efficiency-kpi-grid">
      <div class="stat-card"><div class="stat-label">INTENTOS PRODUCTIVOS</div><div class="stat-value text-success">${escapeHtml(ratio)}</div><div class="stat-sub">${escapeHtml(attempts)} intentos en total (${escapeHtml(reworks)} reintentos correctivos)</div></div>
      <div class="stat-card"><div class="stat-label">IMPLEMENTADOR PRINCIPAL</div><div class="stat-value">${escapeHtml(model)}</div><div class="stat-sub">Proveedor de implementación</div></div>
      <div class="stat-card"><div class="stat-label">REVISOR COMPLEMENTARIO</div><div class="stat-value">${escapeHtml(reviewerModel)}</div><div class="stat-sub">Independencia: <strong>${escapeHtml(independence)}</strong></div></div>
      <div class="stat-card"><div class="stat-label">EJECUCIÓN NATIVA</div><div class="stat-value text-primary">${escapeHtml(selfHost)}</div><div class="stat-sub">Telemetría informada</div></div>
    </div>
    <div class="section-card" style="margin-top: 16px;">
      <h5 class="section-subtitle">Anti-Loop & Retry Telemetry</h5>
      <div class="overview-meta-grid" style="margin-top: 8px;">
        <div class="meta-item"><span class="meta-label">Same-SHA Retries</span><span class="meta-val">${escapeHtml(metrics.same_sha_retry_count ?? 'No informado')}</span></div>
        <div class="meta-item"><span class="meta-label">Same-SHA Suppressed</span><span class="meta-val">${escapeHtml(metrics.same_sha_retry_suppressed_count ?? 'No informado')}</span></div>
        <div class="meta-item"><span class="meta-label">Candidate Generations</span><span class="meta-val">${escapeHtml(metrics.candidate_generations_count ?? 'No informado')}</span></div>
        <div class="meta-item"><span class="meta-label">Reassignments</span><span class="meta-val">${escapeHtml(metrics.reassignments_count ?? 'No informado')}</span></div>
        <div class="meta-item"><span class="meta-label">Evaluated At</span><span class="meta-val">${escapeHtml(formatTimestamp(data.evaluated_at || metrics.updated_at))}</span></div>
      </div>
    </div>
  `;
}

export function renderActionHistory(container, history, formatTimestamp) {
  if (!container) return;
  if (!Array.isArray(history) || !history.length) {
    container.innerHTML = '<p class="table-empty">Aún no hay acciones del operador registradas para este Run.</p>';
    return;
  }
  container.innerHTML = `
    <table class="data-table small-table">
      <thead><tr><th>Time</th><th>Action</th><th>Actor</th><th>Status</th><th>Source</th><th>Summary / Reason</th></tr></thead>
      <tbody>${history.map((item) => {
        const statusClass = item.status === 'SUCCESS' ? 'badge-success' : item.status === 'REJECTED' ? 'badge-warning' : 'badge-danger';
        return `<tr>
          <td>${escapeHtml(formatTimestamp(item.created_at || item.requested_at))}</td>
          <td><span class="badge">${escapeHtml(item.action_type)}</span></td>
          <td><strong>${escapeHtml(item.actor_identity || 'operator')}</strong></td>
          <td><span class="badge ${statusClass}">${escapeHtml(item.status)}</span></td>
          <td><code>${escapeHtml(item.source_interface || 'pwa')}</code></td>
          <td>${escapeHtml(item.message || item.rejection_reason || item.details?.reason || 'Executed')}</td>
        </tr>`;
      }).join('')}</tbody>
    </table>
  `;
}
