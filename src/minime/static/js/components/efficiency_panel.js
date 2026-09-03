export function renderEfficiencyPanel(root, telemetry = null) {
  if (!root) return;
  if (!telemetry || !telemetry.metrics) {
    root.innerHTML = '<div class="card efficiency-card"><h3>Provider Efficiency Telemetry</h3><p class="table-empty">No efficiency metrics recorded yet.</p></div>';
    return;
  }
  const m = telemetry.metrics;
  const attemptsCodex = m.attempts_by_provider?.codex || 0;
  const attemptsAG = m.attempts_by_provider?.antigravity || 0;
  const selfHostingPct = m.self_hosting_percentage ?? 100.0;

  root.innerHTML = `
    <div class="card efficiency-card">
      <div class="card-header">
        <h3>Provider Efficiency & Self-Operating Telemetry</h3>
        <span class="badge ${selfHostingPct >= 80 ? "badge-success" : "badge-warning"}">${selfHostingPct}% Self-Hosted</span>
      </div>
      <div class="grid grid-4" style="margin-top: 1rem;">
        <div class="metric-box">
          <span class="metric-label">Codex Workhorse Attempts</span>
          <span class="metric-value">${attemptsCodex}</span>
        </div>
        <div class="metric-box">
          <span class="metric-label">Antigravity Constrained Attempts</span>
          <span class="metric-value">${attemptsAG}</span>
        </div>
        <div class="metric-box">
          <span class="metric-label">Productive / Corrective</span>
          <span class="metric-value">${m.productive_attempt_count} / ${m.corrective_retry_count}</span>
        </div>
        <div class="metric-box">
          <span class="metric-label">Same-SHA Suppressed</span>
          <span class="metric-value">${m.same_sha_retry_suppressed_count}</span>
        </div>
      </div>
      <div class="efficiency-details" style="margin-top: 1rem; font-size: 0.85rem; color: var(--text-muted);">
        <span>Native Phases: <strong>${m.self_hosting_native_phases} / ${m.self_hosting_total_phases}</strong></span>
        ${m.premium_provider_reason_codes?.length ? ` · <span class="badge badge-info">AG Reason: ${m.premium_provider_reason_codes.join(", ")}</span>` : ""}
      </div>
    </div>
  `;
}
