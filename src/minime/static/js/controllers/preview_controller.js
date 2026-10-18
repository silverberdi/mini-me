/** Owns preview and validation mutations; the UI may only request exact candidate-bound operations. */
export function createPreviewController({ fetchRequest, notify, refresh, getActor }) {
  async function launch({ detail, candidate, button }) {
    if (!candidate?.head_sha || !candidate?.base_sha || !Number.isInteger(candidate.generation) || candidate.generation < 1) {
      notify('No se puede iniciar la vista previa: la identidad del candidato está incompleta.', 'warning');
      return;
    }
    if (button) { button.disabled = true; button.textContent = 'Preparando vista previa…'; }
    try {
      const buildResponse = await fetchRequest('/api/v1/previews/build', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: detail.project_id,
          change_name: detail.change_name,
          run_id: detail.run_id,
          head_sha: candidate.head_sha,
          base_sha: candidate.base_sha,
          candidate_generation: candidate.generation,
        }),
      });
      if (!buildResponse.ok) throw new Error((await buildResponse.json()).detail || `HTTP ${buildResponse.status}`);
      const build = await buildResponse.json();
      if (!build.preview_id) throw new Error('La autoridad no devolvió una identidad de vista previa.');

      if (button) button.textContent = 'Iniciando entorno aislado…';
      const startResponse = await fetchRequest('/api/v1/previews/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ preview_id: build.preview_id, internal_port: 8787, probe_health: true }),
      });
      if (!startResponse.ok) throw new Error((await startResponse.json()).detail || `HTTP ${startResponse.status}`);
      await refresh();
    } catch (error) {
      notify(`No se pudo iniciar la vista previa: ${error.message}`, 'error');
    } finally {
      if (button) { button.disabled = false; button.textContent = 'Iniciar vista previa'; }
    }
  }

  async function teardown({ session, button }) {
    if (!session?.preview_id) return;
    if (button) { button.disabled = true; button.textContent = 'Cerrando entorno…'; }
    try {
      const response = await fetchRequest(`/api/v1/previews/${encodeURIComponent(session.preview_id)}/teardown`, { method: 'POST' });
      if (!response.ok) throw new Error((await response.json()).detail || `HTTP ${response.status}`);
      await refresh();
    } catch (error) {
      notify(`No se pudo cerrar la vista previa: ${error.message}`, 'error');
    } finally {
      if (button) { button.disabled = false; button.textContent = 'Cerrar vista previa'; }
    }
  }

  async function submitValidation({ detail, session, candidate, scenarios, container, verdict, notes, allowed, button }) {
    if (!allowed || !session?.preview_id || !getActor()) {
      notify('No se puede registrar la validación: falta sesión autenticada o evidencia vigente del candidato.', 'warning');
      return null;
    }
    if (session.head_sha !== candidate.head_sha || session.base_sha !== candidate.base_sha
      || session.candidate_generation !== candidate.generation || !session.image_digest || session.status !== 'READY') {
      notify('La vista previa no corresponde exactamente al candidato actual.', 'warning');
      return null;
    }
    const scenarioResults = scenarios.map((scenario) => {
      const steps = Array.from(container.querySelectorAll('.scenario-step-check'))
        .filter((node) => node.dataset.scenarioId === scenario.scenario_id);
      const completion = Array.from(container.querySelectorAll('.scenario-complete-check'))
        .find((node) => node.dataset.scenarioId === scenario.scenario_id);
      const completed = steps.length ? steps.every((step) => step.checked) : Boolean(completion?.checked);
      return { scenario_id: scenario.scenario_id, status: verdict === 'FAIL' ? 'FAIL' : completed ? 'PASS' : 'INCOMPLETE' };
    });
    if (verdict === 'PASS' && scenarios.some((scenario, index) => scenario.required && scenarioResults[index]?.status !== 'PASS')) {
      notify('Completa cada paso requerido antes de registrar PASS.', 'warning');
      return null;
    }

    if (button) { button.disabled = true; button.textContent = 'Registrando…'; }
    try {
      const response = await fetchRequest('/api/v1/validations/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: detail.project_id,
          change_name: detail.change_name,
          run_id: detail.run_id,
          preview_id: session.preview_id,
          candidate_generation: candidate.generation,
          head_sha: candidate.head_sha,
          base_sha: candidate.base_sha,
          image_digest: session.image_digest,
          verdict,
          notes,
          scenario_results: scenarioResults,
        }),
      });
      if (!response.ok) throw new Error((await response.json()).detail || `HTTP ${response.status}`);
      const result = await response.json();
      notify(`Validación ${verdict} registrada por la autoridad para el candidato actual.`, 'success');
      await refresh();
      return result;
    } catch (error) {
      notify(`No se pudo registrar la validación: ${error.message}`, 'error');
      return null;
    } finally {
      if (button) { button.disabled = false; button.textContent = 'Registrar validación'; }
    }
  }

  return { launch, teardown, submitValidation };
}
