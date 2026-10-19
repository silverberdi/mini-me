const escapeHtml = (value) => String(value ?? '').replace(/[&<>\"']/g, (character) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;', "'": '&#39;',
})[character]);

export function renderGitHubEvidence(container, github, sanitizeUrl) {
  if (!container) return;
  if (!github || (!github.issue_number && !github.pr_number)) {
    container.innerHTML = '<p class="text-muted">No hay un Issue o Pull Request de GitHub vinculado a este cambio.</p>';
    return;
  }
  container.innerHTML = `<div class="overview-meta-grid">
    <div class="meta-box"><div class="meta-box-label">GitHub Issue</div><div class="meta-box-val">${github.issue_url ? `<a href="${sanitizeUrl(github.issue_url)}" target="_blank" rel="noopener noreferrer">#${escapeHtml(github.issue_number)} ↗</a>` : github.issue_number ? `#${escapeHtml(github.issue_number)}` : '---'}</div></div>
    <div class="meta-box"><div class="meta-box-label">Pull Request</div><div class="meta-box-val">${github.pr_url ? `<a href="${sanitizeUrl(github.pr_url)}" target="_blank" rel="noopener noreferrer">PR #${escapeHtml(github.pr_number)} ↗</a>` : github.pr_number ? `PR #${escapeHtml(github.pr_number)}` : 'No creado'}</div></div>
    <div class="meta-box"><div class="meta-box-label">Estado del PR</div><div class="meta-box-val"><span class="badge ${github.is_merged ? 'badge-completed' : github.pr_state === 'open' ? 'badge-ready' : 'badge-not-ready'}">${github.is_merged ? 'MERGED' : github.pr_state ? escapeHtml(github.pr_state.toUpperCase()) : 'PENDING'}</span></div></div>
    <div class="meta-box"><div class="meta-box-label">Vinculado al candidato</div><div class="meta-box-val">${github.candidate_bound ? '<span class="text-success">✓ Vinculado</span>' : '<span class="text-muted">Pendiente</span>'}</div></div>
  </div>`;
}

export function renderTimelineEvidence(container, timeline, formatTimestamp) {
  if (!container) return;
  if (!Array.isArray(timeline) || !timeline.length) {
    container.innerHTML = '<p class="text-muted">No hay eventos del ciclo de vida para este cambio.</p>';
    return;
  }
  container.innerHTML = timeline.map((event) => `<div class="timeline-entry">
    <div class="timeline-time">${escapeHtml(formatTimestamp(event.timestamp))}</div>
    <div class="timeline-title">${escapeHtml(event.summary)}</div>
    <div class="timeline-desc">Evento: <span class="font-mono">${escapeHtml(event.event_type)}</span> | Actor: ${escapeHtml(event.actor || 'system')}</div>
  </div>`).join('');
}
