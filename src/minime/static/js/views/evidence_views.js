const escapeHtml = (value) => String(value ?? "").replace(/[&<>\"']/g, (character) => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  "\"": "&quot;",
  "'": "&#039;",
}[character]));

export function renderCandidateEvidence({ summary, history, detail }) {
  if (summary) {
    const authority = detail.candidate_authority;
    summary.innerHTML = authority ? `
      <div class="overview-meta-grid">
        <div class="meta-box"><div class="meta-box-label">SHA del candidato actual</div><div class="meta-box-val"><code class="code-sha">${escapeHtml(authority.candidate_sha)}</code></div></div>
        <div class="meta-box"><div class="meta-box-label">SHA base</div><div class="meta-box-val"><code class="code-sha">${escapeHtml(authority.base_sha)}</code></div></div>
        <div class="meta-box"><div class="meta-box-label">Generación</div><div class="meta-box-val">Generación ${escapeHtml(authority.generation)} ${authority.is_frozen ? "(Congelada)" : "(Activa)"}</div></div>
        <div class="meta-box"><div class="meta-box-label">Hash del manifiesto</div><div class="meta-box-val font-mono text-muted">${escapeHtml(authority.manifest_hash || "—")}</div></div>
      </div>
      ${authority.changed_files?.length ? `<div style="margin-top:12px"><div class="meta-box-label" style="margin-bottom:4px">Archivos modificados (${authority.changed_files.length})</div><ul style="padding-left:20px;font-family:var(--font-mono);font-size:11px;color:var(--text-muted)">${authority.changed_files.map((file) => `<li>${escapeHtml(file)}</li>`).join("")}</ul></div>` : ""}
    ` : '<p class="text-muted">No hay una generación de candidato finalizada.</p>';
  }
  if (history) {
    history.innerHTML = detail.candidate_history?.length ? detail.candidate_history.map((candidate) => `
      <tr><td><strong>gen-${escapeHtml(candidate.generation)}</strong></td><td><code class="code-sha">${escapeHtml(candidate.candidate_sha_short)}</code></td><td><code class="code-sha">${escapeHtml(candidate.base_sha_short)}</code></td><td>${candidate.is_superseded ? '<span class="badge badge-not-ready">OBSOLETO</span>' : '<span class="badge badge-ready">ACTUAL</span>'}</td><td class="font-mono text-muted">${escapeHtml(candidate.created_at || "—")}</td></tr>
    `).join("") : '<tr><td colspan="5" class="table-empty">No hay historial de candidatos.</td></tr>';
  }
}

export function renderRunOverview({ metaGrid, blockerSection, blockersList, detail }) {
  if (metaGrid) {
    metaGrid.innerHTML = `
      <div class="meta-box"><div class="meta-box-label">Etapa actual</div><div class="meta-box-val">${escapeHtml(detail.current_stage || "UNKNOWN")}</div></div>
      <div class="meta-box"><div class="meta-box-label">Resultado de detención</div><div class="meta-box-val">${escapeHtml(detail.stop_outcome || "UNKNOWN")}</div></div>
      <div class="meta-box"><div class="meta-box-label">ID de Run</div><div class="meta-box-val font-mono text-muted">${escapeHtml(detail.run_id || "—")}</div></div>
      <div class="meta-box"><div class="meta-box-label">ID de Job activo</div><div class="meta-box-val font-mono text-muted">${escapeHtml(detail.job_id || "—")}</div></div>
      <div class="meta-box"><div class="meta-box-label">Ejecutor asignado</div><div class="meta-box-val">${escapeHtml(detail.current_executor || "UNKNOWN")}</div></div>
      <div class="meta-box"><div class="meta-box-label">Rama destino</div><div class="meta-box-val font-mono">${escapeHtml(detail.target_branch || "UNKNOWN")}</div></div>
      <div class="meta-box"><div class="meta-box-label">Gate humano</div><div class="meta-box-val">${escapeHtml(detail.human_gate || "UNKNOWN")}</div></div>`;
  }
  const blockers = Array.isArray(detail.blocker_details) ? detail.blocker_details : [];
  if (blockerSection) blockerSection.style.display = blockers.length ? "block" : "none";
  if (blockersList) blockersList.innerHTML = blockers.map((blocker) => `
    <div class="attention-item-card"><div class="attention-item-left"><span class="attention-item-name">${escapeHtml(blocker.type || blocker.claim_type || "BLOCKER")}</span><span class="attention-item-reason">${escapeHtml(blocker.reason || blocker.description || "")}</span></div>${blocker.human_gate ? `<span class="badge badge-needs-human">${escapeHtml(blocker.human_gate)}</span>` : ""}</div>`).join("");
}

export function renderChecksEvidence({ count, container, checks }) {
  if (count) count.textContent = Array.isArray(checks) ? String(checks.length) : "—";
  if (!container) return;
  if (!checks?.length) {
    container.innerHTML = '<p class="text-muted">No hay resultados de verificaciones determinísticas.</p>';
    return;
  }
  container.innerHTML = checks.map((check) => {
    const passed = check.status === "PASS" || check.exit_code === 0;
    return `<div class="check-item"><div class="check-item-left"><div class="check-item-title">${escapeHtml(check.check_name)}</div><div class="check-item-cmd">${escapeHtml(check.command)}</div>${check.diagnostic_snippet ? `<div class="check-diagnostic">${escapeHtml(check.diagnostic_snippet)}</div>` : ""}</div><div class="check-item-meta"><span class="text-muted check-duration">${check.duration_ms ? `${escapeHtml(check.duration_ms)}ms` : ""}</span><span class="badge ${passed ? "badge-ready" : "badge-failed"}">${passed ? "PASS" : "FAIL"}</span></div></div>`;
  }).join("");
}

export function renderReviewEvidence({ container, review, candidate }) {
  if (!container) return;
  if (!review || review.status === "not_started") {
    container.innerHTML = '<p class="text-muted">La revisión complementaria aún no se ha ejecutado.</p>';
    return;
  }
  const candidateBound = Boolean(review.candidate_sha && candidate?.candidate_sha && review.candidate_sha === candidate.candidate_sha);
  const stale = review.is_stale_to_current_candidate === true || Boolean(review.candidate_sha && candidate?.candidate_sha && review.candidate_sha !== candidate.candidate_sha);
  const passes = review.verdict === "READY_TO_MERGE" && candidateBound && !stale;
  const binding = candidateBound ? "VIGENTE" : stale ? "OBSOLETA" : "DESCONOCIDA";
  container.innerHTML = `
    <div class="overview-meta-grid" style="margin-bottom:12px">
      <div class="meta-box"><div class="meta-box-label">Rol del revisor</div><div class="meta-box-val">${escapeHtml(review.reviewer_role || "No informado")}</div></div>
      <div class="meta-box"><div class="meta-box-label">Veredicto</div><div class="meta-box-val"><span class="badge ${passes ? "badge-ready" : "badge-failed"}">${escapeHtml(review.verdict || review.status)}</span></div></div>
      <div class="meta-box"><div class="meta-box-label">Hallazgos relevantes</div><div class="meta-box-val">${escapeHtml(review.material_findings_count ?? "—")}</div></div>
      <div class="meta-box"><div class="meta-box-label">Vinculación del candidato</div><div class="meta-box-val"><code class="code-sha">${escapeHtml(review.candidate_sha ? review.candidate_sha.substring(0, 8) : "—")}</code> <span class="badge ${candidateBound ? "badge-ready" : stale ? "badge-warning" : "badge-muted"}">${binding}</span></div></div>
    </div>
    ${review.summary ? `<div class="meta-box review-summary"><div class="meta-box-label">Resumen de la revisión</div><p>${escapeHtml(review.summary)}</p></div>` : ""}
    ${review.findings?.length ? `<div class="meta-box-label">Hallazgos (${review.findings.length})</div><div class="checks-list">${review.findings.map((finding) => `<div class="check-item"><div class="check-item-left"><div class="check-item-title">${escapeHtml(finding.severity)}: ${escapeHtml(finding.location || "Codebase")}</div><div class="text-muted">${escapeHtml(finding.violated_requirement || finding.expected_correction || "")}</div></div><span class="badge ${finding.severity === "BLOCKER" ? "badge-failed" : "badge-waiting"}">${escapeHtml(finding.severity)}</span></div>`).join("")}</div>` : '<p class="text-muted">No se informaron hallazgos.</p>'}
  `;
}

export function renderAuditEvidence({ container, audit, candidate }) {
  if (!container) return;
  if (!audit || audit.status === "not_started") {
    container.innerHTML = '<p class="text-muted">La auditoría independiente aún no se ha ejecutado.</p>';
    return;
  }
  const candidateBound = Boolean(audit.candidate_sha && candidate?.candidate_sha && audit.candidate_sha === candidate.candidate_sha);
  const stale = audit.is_stale_to_current_candidate === true || Boolean(audit.candidate_sha && candidate?.candidate_sha && audit.candidate_sha !== candidate.candidate_sha);
  const risk = audit.risk || "UNKNOWN";
  container.innerHTML = `
    <div class="overview-meta-grid" style="margin-bottom:12px">
      <div class="meta-box"><div class="meta-box-label">Auditor</div><div class="meta-box-val">${escapeHtml(audit.provider || "No informado")} / ${escapeHtml(audit.model || "No informado")}</div></div>
      <div class="meta-box"><div class="meta-box-label">Nivel de riesgo</div><div class="meta-box-val"><span class="badge ${risk === "low" ? "badge-ready" : audit.risk ? "badge-failed" : "badge-muted"}">RIESGO: ${escapeHtml(risk)}</span></div></div>
      <div class="meta-box"><div class="meta-box-label">Hallazgos relevantes</div><div class="meta-box-val">${escapeHtml(audit.material_findings_count ?? "—")}</div></div>
      <div class="meta-box"><div class="meta-box-label">Vinculación del candidato</div><div class="meta-box-val"><code class="code-sha">${escapeHtml(audit.candidate_sha ? audit.candidate_sha.substring(0, 8) : "—")}</code> <span class="badge ${candidateBound ? "badge-ready" : stale ? "badge-warning" : "badge-muted"}">${candidateBound ? "VIGENTE" : stale ? "OBSOLETA" : "DESCONOCIDA"}</span></div></div>
    </div>
    ${audit.summary ? `<div class="meta-box review-summary"><div class="meta-box-label">Resumen de auditoría</div><p>${escapeHtml(audit.summary)}</p></div>` : ""}
    ${audit.findings?.length ? `<div class="meta-box-label">Hallazgos (${audit.findings.length})</div><div class="checks-list">${audit.findings.map((finding) => `<div class="check-item"><div class="check-item-left"><div class="check-item-title">${escapeHtml((finding.severity || "UNKNOWN").toUpperCase())}: ${escapeHtml(finding.category || "General")}</div><div class="text-muted">${escapeHtml(finding.message || "")}</div></div><span class="badge ${finding.severity === "critical" || finding.severity === "high" ? "badge-failed" : "badge-waiting"}">${escapeHtml((finding.severity || "UNKNOWN").toUpperCase())}</span></div>`).join("")}</div>` : '<p class="text-muted">No se informaron hallazgos de seguridad o integridad.</p>'}
  `;
}
