/** Owns the request/result lifecycle for governed Control Plane actions. */
const humanOnlyActionTypes = new Set(['merge', 'merge_pr', 'merge_pull_request', 'merge_github_pr']);

function completedActionMessage(actionType, result) {
  const type = String(actionType || '').toUpperCase();
  if (type === 'CANCEL') {
    return result.status === 'COMPLETED' ? 'Ejecución cancelada.' : 'Solicitud de cancelación aceptada.';
  }
  const messages = {
    CONTINUE: 'Continuación solicitada.',
    REASSIGN: 'Reasignación completada.',
    RETRY: 'Reintento solicitado.',
    RESOLVE_GATE: 'Decisión registrada.',
    START_PREVIEW: 'Vista previa solicitada.',
    TEARDOWN_PREVIEW: 'Cierre de vista previa solicitado.',
  };
  return messages[type] || 'Acción completada.';
}

export function visibleControlPlaneActions(actions) {
  return (Array.isArray(actions) ? actions : []).filter((action) => {
    const actionType = String(action.action || action.action_type || '').trim().toLowerCase();
    return actionType && !humanOnlyActionTypes.has(actionType);
  });
}

export function createActionController({
  execute,
  discover,
  notify,
  refreshOverview,
  refreshSelectedDetail,
  getActor,
  toolbar,
  mobileNextStep,
  escapeHtml = (value) => String(value ?? '').replace(/[&<>\"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;', "'": '&#39;',
  })[character]),
  openParameters = () => false,
  openConfirmation = () => false,
}) {
  let toolbarBound = false;
  let toolbarRenderSequence = 0;
  let displayedActions = [];
  let displayedDetail = null;

  function bindToolbar() {
    if (!toolbar || toolbarBound) return;
    toolbarBound = true;
    toolbar.addEventListener('click', (event) => {
      const button = event.target.closest('[data-action]:not(:disabled)');
      if (!button || !toolbar.contains(button)) return;
      const action = displayedActions.find((item) => (item.action || item.action_type) === button.dataset.action);
      if (action && displayedDetail) handleActionClick(action, displayedDetail);
    });
  }

  function renderMobileActions(actions) {
    if (!mobileNextStep) return;
    const enabled = actions.filter((action) => action.enabled === true);
    const labels = enabled.map((action) => {
      const type = String(action.action || action.action_type || '').toUpperCase();
      const knownLabels = {
        CANCEL: 'Cancelar ejecución',
        CONTINUE: 'Continuar ejecución',
        REASSIGN: 'Reasignar ejecutor',
        RETRY: 'Reintentar etapa',
        RESOLVE_GATE: 'Resolver decisión humana',
        RECOVER_LOCKS: 'Recuperar bloqueos',
        AUTHORIZE_DEEPSEEK_REVIEW: 'Autorizar revisión del contrato',
        AUTHORIZE_DEEPSEEK_CODE_REVIEW: 'Autorizar revisión del código',
      };
      return knownLabels[type] || action.display_name || type;
    });
    mobileNextStep.textContent = labels.length
      ? `Acciones habilitadas por Control Plane: ${labels.join(' · ')}`
      : 'Siguiente paso: el Control Plane no informa acciones habilitadas.';
  }

  async function renderToolbar(detail) {
    if (!toolbar) return;
    const requestSequence = ++toolbarRenderSequence;
    const runId = detail?.run_id;
    displayedDetail = detail || null;
    displayedActions = [];
    toolbar.innerHTML = runId
      ? '<span class="text-muted" role="status">Cargando acciones…</span>'
      : '';
    if (mobileNextStep) {
      mobileNextStep.textContent = runId
        ? 'Siguiente paso: consultando acciones autorizadas…'
        : 'Siguiente paso: no disponible para este cambio.';
    }
    if (!runId) {
      return;
    }
    try {
      const actions = visibleControlPlaneActions(await discover(runId));
      if (requestSequence !== toolbarRenderSequence || displayedDetail?.run_id !== runId) return;
      displayedActions = actions;
      renderMobileActions(displayedActions);
      if (!displayedActions.length) {
        toolbar.innerHTML = '<span class="text-muted">No hay acciones disponibles</span>';
        return;
      }
      toolbar.innerHTML = displayedActions.map((action) => {
        const actionType = action.action || action.action_type;
        const normalized = actionType.toLowerCase();
        const buttonClass = ['cancel', 'recover_locks'].includes(normalized)
          ? 'btn-danger'
          : ['continue', 'resolve_gate'].includes(normalized) ? 'btn-primary' : 'btn-secondary';
        const disabled = action.enabled === false ? 'disabled' : '';
        const tooltip = action.disabled_reason || action.description || '';
        return `<button type="button" class="btn btn-sm ${buttonClass}" data-action="${escapeHtml(actionType)}" ${disabled} title="${escapeHtml(tooltip)}">${escapeHtml(action.display_name || actionType)}</button>`;
      }).join(' ');
    } catch {
      if (requestSequence !== toolbarRenderSequence) return;
      displayedActions = [];
      if (mobileNextStep) mobileNextStep.textContent = 'Siguiente paso: acciones no disponibles.';
      toolbar.innerHTML = '<span class="text-muted">Acciones del operador no disponibles</span>';
    }
  }

  function handleActionClick(action, detail) {
    const actionType = (action.action || action.action_type || '').toLowerCase();
    const submit = (type, parameters = {}) => executeAction(detail, type, parameters);
    if (actionType === 'reassign') {
      openParameters({
        title: 'Reasignar ejecutor',
        description: `Selecciona el proveedor de ejecución para «${detail.change_name}».`,
        fields: [
          { name: 'executor', label: 'Ejecutor de destino', type: 'select', options: [
            { value: 'codex', label: 'Codex (implementación)' },
            { value: 'antigravity', label: 'Antigravity (supervisión)' },
          ], default: 'codex' },
          { name: 'rationale', label: 'Motivo de la reasignación (opcional)', type: 'text', placeholder: 'Explica el motivo del relevo…' },
        ],
        onSubmit: (params) => submit('REASSIGN', { target_executor: params.executor, rationale: params.rationale || '' }),
      });
    } else if (actionType === 'resolve_gate') {
      openParameters({
        title: 'Resolver compuerta humana',
        description: `Resolver la compuerta de «${detail.change_name}» (${detail.human_gate || 'desconocida'}).`,
        fields: [
          { name: 'resolution', label: 'Decisión', type: 'select', options: [
            { value: 'APPROVED', label: 'Aprobar (continuar)' },
            { value: 'REJECTED', label: 'Rechazar (solicitar cambios)' },
            { value: 'OVERRIDDEN', label: 'Anular compuerta' },
          ], default: 'APPROVED' },
          { name: 'notes', label: 'Notas de la decisión', type: 'textarea', placeholder: 'Añade notas o el motivo de la decisión…' },
        ],
        onSubmit: (params) => submit('RESOLVE_GATE', { gate_action: params.resolution, operator_notes: params.notes || '' }),
      });
    } else if (actionType === 'retry') {
      openParameters({
        title: 'Reintentar etapa',
        description: `Reintentar la etapa de «${detail.change_name}».`,
        fields: [{ name: 'reason', label: 'Motivo del reintento (opcional)', type: 'text', placeholder: 'Motivo del reintento…' }],
        onSubmit: (params) => submit('RETRY', { reason: params.reason || 'Operator manual retry' }),
      });
    } else if (action.requires_confirmation || ['cancel', 'recover_locks', 'reconcile_post_merge'].includes(actionType)) {
      openConfirmation({
        title: action.display_name || `Confirm ${actionType.toUpperCase()}`,
        description: action.confirmation_prompt || action.description || `Confirm execution of ${action.display_name || actionType}.`,
        warning: actionType === 'cancel' ? 'Esto cancelará la ejecución activa y liberará sus recursos.' : actionType === 'recover_locks' ? 'Esto intentará recuperar los bloqueos obsoletos de esta ejecución.' : '',
        meta: {
          Change: detail.change_name,
          'Run ID': detail.run_id ? `${detail.run_id.slice(0, 8)}...` : '---',
          'Etapa actual': detail.current_stage || '—',
          'Nivel de riesgo': action.risk_level || 'UNKNOWN',
        },
        onConfirm: () => submit(action.action || action.action_type),
      });
    } else {
      submit(action.action || action.action_type);
    }
  }

  async function executeAction(detail, actionType, parameters = {}) {
    const runId = detail?.run_id;
    if (!runId) {
      notify('No se puede ejecutar la acción: el cambio no tiene un Run activo.', 'error');
      return;
    }

    const payload = {
      action_request_id: crypto.randomUUID(),
      project_id: detail.project_id,
      change_name: detail.change_name,
      run_id: runId,
      action_type: String(actionType).toUpperCase(),
      parameters,
      actor_identity: getActor() || 'operator',
      source_interface: 'pwa',
      expected_stage: detail.current_stage || null,
      expected_generation: detail.candidate_authority?.generation || detail.generation || null,
      expected_candidate_sha: detail.candidate_authority?.candidate_sha || detail.candidate_sha || null,
      expected_human_gate: detail.human_gate || null,
      requested_at: new Date().toISOString(),
    };

    try {
      notify(`Ejecutando ${actionType}…`, 'info');
      const result = await execute(runId, payload);
      const accepted = ['SUCCESS', 'COMPLETED', 'ACCEPTED'].includes(result.status) || result.success === true;
      if (accepted) {
        notify(completedActionMessage(actionType, result), 'success');
      } else {
        const message = result.summary || result.error_message || result.error_code || result.detail || result.message || 'La acción fue rechazada o falló.';
        notify(`Falló la acción: ${message}`, 'error');
      }
      await refreshOverview();
      await refreshSelectedDetail();
      return result;
    } catch (error) {
      const message = error.payload?.summary || error.payload?.error_message || error.payload?.error_code || error.message;
      notify(`Falló la acción: ${message}`, 'error');
      await refreshOverview();
      return null;
    }
  }

  return { bindToolbar, renderToolbar, executeAction };
}
