const escapeHtml = (value) => String(value ?? '').replace(/[&<>\"']/g, (character) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;', "'": '&#39;',
})[character]);

export function renderPreviewView({ previewVal, detail, elements, previewActions, sanitizeUrl, formatRelativeTime }) {
  const { status, scenarios, history, launchButton, teardownButton } = elements;
  if (!status || !scenarios || !history) return;
  const session = previewVal?.preview_session || null;
  const candidate = detail.candidate_authority || {};
  const headSha = candidate.candidate_sha || null;
  const baseSha = candidate.base_sha || null;
  const generation = candidate.generation;
  const identityValid = Boolean(headSha && baseSha && Number.isInteger(generation) && generation > 0);
  const bound = Boolean(session && identityValid
    && session.head_sha === headSha
    && session.base_sha === baseSha
    && Number(session.candidate_generation) === generation
    && session.image_digest);
  const validationAllowed = bound && session.status === 'READY' && !previewVal?.is_stale;

  if (session && ['READY', 'STARTING', 'PROBING'].includes(session.status)) {
    if (launchButton) launchButton.style.display = 'none';
    if (teardownButton) {
      teardownButton.style.display = 'inline-block';
      teardownButton.onclick = () => previewActions.teardown({ session, button: teardownButton });
    }
  } else {
    if (teardownButton) teardownButton.style.display = 'none';
    if (launchButton) {
      launchButton.style.display = 'inline-block';
      launchButton.disabled = !identityValid;
      launchButton.title = identityValid
        ? 'Crear vista previa para la identidad exacta del candidato'
        : 'No disponible: falta identidad verificable de candidato, base o generación';
      launchButton.onclick = () => previewActions.launch({
        detail,
        candidate: { head_sha: headSha, base_sha: baseSha, generation },
        button: launchButton,
      });
    }
  }

  if (!session) {
    const required = previewVal?.is_preview_required === true;
    status.innerHTML = `<div class="overview-meta-grid" style="margin-bottom:8px">
      <div class="meta-box"><div class="meta-box-label">Requisito de vista previa</div><div class="meta-box-val">${required ? '<span class="badge badge-warning">REQUERIDA PARA INTEGRAR</span>' : '<span class="text-muted">Opcional</span>'}</div></div>
      <div class="meta-box"><div class="meta-box-label">Estado</div><div class="meta-box-val"><span class="badge badge-discovered">NO INICIADA</span></div></div>
      <div class="meta-box"><div class="meta-box-label">Veredicto de validación</div><div class="meta-box-val"><span class="badge badge-not-ready">PENDIENTE</span></div></div>
    </div><p class="text-muted">Inicia una vista previa aislada para el candidato seleccionado.</p>`;
  } else {
    const ready = session.status === 'READY';
    const authorized = previewVal?.is_authorized === true;
    const stale = previewVal?.is_stale === true;
    const tone = ready ? 'badge-ready' : session.status === 'FAILED' ? 'badge-failed' : 'badge-running';
    status.innerHTML = `<div class="overview-meta-grid" style="margin-bottom:12px">
      <div class="meta-box"><div class="meta-box-label">Estado de la vista previa</div><div class="meta-box-val"><span class="badge ${tone}">${escapeHtml(session.status)}</span></div></div>
      <div class="meta-box"><div class="meta-box-label">URL de la vista previa</div><div class="meta-box-val">${session.preview_url ? `<a href="${sanitizeUrl(session.preview_url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(session.preview_url)} ↗</a>` : '<span class="text-muted">---</span>'}</div></div>
      <div class="meta-box"><div class="meta-box-label">Puerto asignado</div><div class="meta-box-val">${escapeHtml(session.allocated_port ?? '---')}</div></div>
      <div class="meta-box"><div class="meta-box-label">Autoridad de validación</div><div class="meta-box-val">${authorized ? '<span class="badge badge-completed">APROBACIÓN REGISTRADA</span>' : stale ? '<span class="badge badge-warning">OBSOLETA (REQUIERE REVALIDACIÓN)</span>' : '<span class="badge badge-not-ready">REQUIERE VALIDACIÓN</span>'}</div></div>
    </div><div class="meta-box"><div class="meta-box-label">Digest inmutable de imagen</div><div class="meta-box-val font-mono">${escapeHtml(session.image_digest || '---')}</div></div>
    ${session.failure_reason ? `<div class="meta-box"><div class="meta-box-label text-danger">Diagnóstico (${escapeHtml(session.failure_code || 'ERROR')})</div><p>${escapeHtml(session.failure_reason)}</p></div>` : ''}`;
  }

  const scenarioList = Array.isArray(previewVal?.scenarios) ? previewVal.scenarios : [];
  if (!scenarioList.length) {
    scenarios.innerHTML = '<p class="text-muted">No hay escenarios de validación definidos para este cambio.</p>';
  } else {
    scenarios.innerHTML = `<div class="checks-list">${scenarioList.map((scenario) => `<div class="check-item" style="flex-direction:column;align-items:flex-start;gap:6px">
      <div class="check-item-title">${escapeHtml(scenario.title)}</div><span class="badge ${scenario.required ? 'badge-ready' : 'badge-discovered'}">${scenario.required ? 'Obligatorio' : 'Opcional'}</span>
      <p>${escapeHtml(scenario.description)}</p>${scenario.ordered_steps?.length ? scenario.ordered_steps.map((step, index) => `<label><input type="checkbox" class="scenario-step-check" data-scenario-id="${escapeHtml(scenario.scenario_id)}" data-step-idx="${index}"><span>${escapeHtml(step)}</span></label>`).join('') : `<label class="validation-scenario-completion"><input type="checkbox" class="scenario-complete-check" data-scenario-id="${escapeHtml(scenario.scenario_id)}"><span>Confirmo que completé este escenario.</span></label>`}
    </div>`).join('')}</div><div class="validation-submission-form">
      <h5>Registrar validación del candidato</h5><label for="validationVerdictSelect">Veredicto</label><select id="validationVerdictSelect"><option value="PASS">PASS — Validación visual completada</option><option value="FAIL">FAIL — Se observaron defectos</option></select>
      <p id="validationOperatorIdentity">La validación se registrará con la identidad autenticada.</p><label for="validationNotesInput">Notas u observaciones</label><textarea id="validationNotesInput" rows="2"></textarea>
      <button id="submitValidationBtn" class="btn btn-primary btn-sm" ${validationAllowed ? '' : 'disabled'}>Registrar validación</button>${validationAllowed ? '' : '<p class="text-muted">No disponible: falta una vista previa READY vinculada a este candidato o la evidencia está obsoleta.</p>'}
    </div>`;
    const submitButton = scenarios.querySelector('#submitValidationBtn');
    submitButton?.addEventListener('click', () => previewActions.submitValidation({
      detail, session, candidate: { head_sha: headSha, base_sha: baseSha, generation },
      scenarios: scenarioList, container: scenarios,
      verdict: scenarios.querySelector('#validationVerdictSelect')?.value,
      notes: scenarios.querySelector('#validationNotesInput')?.value || '',
      allowed: validationAllowed, button: submitButton,
    }), { once: true });
  }

  const historyList = Array.isArray(previewVal?.validation_history) ? previewVal.validation_history : [];
  history.innerHTML = historyList.length ? `<table class="data-table small-table"><thead><tr><th>Veredicto</th><th>SHA candidato</th><th>Digest imagen</th><th>Operador</th><th>Registrado</th><th>Autoridad</th></tr></thead><tbody>${historyList.map((item) => `<tr>
    <td><span class="badge ${item.verdict === 'PASS' ? 'badge-ready' : 'badge-failed'}">${escapeHtml(item.verdict)}</span></td><td><code>${escapeHtml(item.head_sha_short || item.head_sha?.substring(0, 8) || '---')}</code></td><td><code>${escapeHtml(item.image_digest ? `${item.image_digest.substring(0, 15)}...` : '---')}</code></td><td>${escapeHtml(item.operator || 'operator')}</td><td>${escapeHtml(formatRelativeTime(item.created_at))}</td><td>${item.is_stale ? '<span class="badge badge-warning">STALE</span>' : '<span class="text-success">CURRENT</span>'}</td>
  </tr>`).join('')}</tbody></table>` : '<p class="text-muted">No hay validaciones históricas registradas.</p>';
}

export const previewView = 'preview';
