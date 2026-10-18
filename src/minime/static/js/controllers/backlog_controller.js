/** Owns authenticated Backlog API mutations and their post-write reconciliation. */
export function createBacklogController({ fetchRequest, notify, getProjectId, refreshBacklog, refreshProjects, selectItem, clearSelectedItem, onStarted, confirmAction }) {
  let searchQuery = '';
  let filter = 'ALL';
  let bound = false;
  async function request(url, init, successMessage) {
    const response = await fetchRequest(url, init);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `HTTP ${response.status}`);
    }
    if (successMessage) notify(successMessage, 'success');
    return response.status === 204 ? null : response.json();
  }

  async function prepare(itemKey) {
    const projectId = getProjectId();
    try {
      const result = await request(`/api/v1/projects/${encodeURIComponent(projectId)}/backlog/${encodeURIComponent(itemKey)}/prepare`, { method: 'POST' });
      notify(`Artefactos preparados. Estado: ${result.status}`, result.status === 'READY' ? 'success' : 'warning');
      await refreshBacklog(projectId);
      selectItem(itemKey);
      return result;
    } catch (error) { notify(`No se pudieron preparar los artefactos: ${error.message}`, 'error'); return null; }
  }

  async function start(itemKey) {
    const projectId = getProjectId();
    try {
      const result = await request(`/api/v1/projects/${encodeURIComponent(projectId)}/backlog/${encodeURIComponent(itemKey)}/start`, { method: 'POST' });
      notify(`Trabajo admitido. Run: ${result.run_id}`, 'success');
      await refreshBacklog(projectId);
      selectItem(itemKey);
      onStarted();
      return result;
    } catch (error) { notify(`No se pudo iniciar el trabajo: ${error.message}`, 'error'); return null; }
  }

  async function answer(itemKey, answerText) {
    const projectId = getProjectId();
    try {
      await request(`/api/v1/projects/${encodeURIComponent(projectId)}/backlog/${encodeURIComponent(itemKey)}/answer`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ answer: answerText }),
      }, 'Aclaración registrada; se volverá a evaluar la preparación.');
      await refreshBacklog(projectId);
      selectItem(itemKey);
      return true;
    } catch (error) { notify(`No se pudo registrar la aclaración: ${error.message}`, 'error'); return false; }
  }

  async function save(item, editingKey) {
    const projectId = getProjectId();
    const url = editingKey
      ? `/api/v1/projects/${encodeURIComponent(projectId)}/backlog/${encodeURIComponent(editingKey)}`
      : `/api/v1/projects/${encodeURIComponent(projectId)}/backlog`;
    const result = await request(url, {
      method: editingKey ? 'PATCH' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(item),
    });
    const itemKey = editingKey || result.item_key;
    notify(editingKey ? `Trabajo ${itemKey} actualizado.` : `Trabajo ${itemKey} creado.`, 'success');
    await refreshBacklog(projectId);
    selectItem(itemKey);
    return result;
  }

  async function remove(itemKey) {
    if (!confirmAction(`¿Eliminar el elemento ${itemKey}?`)) return false;
    const projectId = getProjectId();
    try {
      await request(`/api/v1/projects/${encodeURIComponent(projectId)}/backlog/${encodeURIComponent(itemKey)}`, { method: 'DELETE' });
      notify(`Trabajo ${itemKey} eliminado.`, 'info');
      clearSelectedItem();
      await refreshBacklog(projectId);
      return true;
    } catch (error) { notify(`No se pudo eliminar el trabajo: ${error.message}`, 'error'); return false; }
  }

  async function discover(projectId = getProjectId()) {
    try {
      const result = await request(`/api/v1/projects/${encodeURIComponent(projectId)}/context/discover`, { method: 'POST' });
      notify(`Exploración completada. Elementos encontrados: ${result.discovered_items_count}`, 'success');
      await refreshProjects();
      await refreshBacklog(projectId);
      return result;
    } catch (error) { notify(`No se pudo explorar el contexto: ${error.message}`, 'error'); return null; }
  }

  function bindEvents({
    searchInput,
    statusPills,
    tableBody,
    newItemButton,
    cancelButton,
    itemModal,
    itemForm,
    discoverButton,
    prepareButton,
    startButton,
    editButton,
    deleteButton,
    answerForm,
    answerInput,
    runArtifact,
    getSelectedItem,
    openEditor,
    saveForm,
    renderTable,
    clearAnswer,
    onOpenRun,
  }) {
    if (bound) return;
    bound = true;
    searchInput?.addEventListener('input', (event) => {
      searchQuery = event.target.value.toLowerCase().trim();
      renderTable();
    });
    statusPills.forEach((pill) => pill.addEventListener('click', () => {
      statusPills.forEach((entry) => entry.classList.remove('active'));
      pill.classList.add('active');
      filter = pill.getAttribute('data-backlog-filter');
      renderTable();
    }));
    tableBody?.addEventListener('click', (event) => {
      const actionButton = event.target.closest('[data-backlog-action]');
      if (actionButton) {
        event.stopPropagation();
        const itemKey = actionButton.dataset.itemKey;
        if (actionButton.dataset.backlogAction === 'prepare') void prepare(itemKey);
        if (actionButton.dataset.backlogAction === 'start') void start(itemKey);
        return;
      }
      const row = event.target.closest('[data-item-key]');
      if (row) selectItem(row.getAttribute('data-item-key'));
    });
    newItemButton?.addEventListener('click', () => openEditor());
    cancelButton?.addEventListener('click', () => itemModal?.close());
    itemForm?.addEventListener('submit', (event) => {
      event.preventDefault();
      void saveForm();
    });
    discoverButton?.addEventListener('click', () => { void discover(); });
    prepareButton?.addEventListener('click', () => {
      const item = getSelectedItem();
      if (item) void prepare(item.item_key);
    });
    startButton?.addEventListener('click', () => {
      const item = getSelectedItem();
      if (item) void start(item.item_key);
    });
    editButton?.addEventListener('click', () => {
      const item = getSelectedItem();
      if (item) openEditor(item);
    });
    deleteButton?.addEventListener('click', async () => {
      const item = getSelectedItem();
      if (item) await remove(item.item_key);
    });
    answerForm?.addEventListener('submit', async (event) => {
      event.preventDefault();
      const item = getSelectedItem();
      const answerText = answerInput?.value.trim();
      if (item && answerText && await answer(item.item_key, answerText)) clearAnswer();
    });
    runArtifact?.addEventListener('click', (event) => {
      if (event.target.closest('[data-open-run]')) onOpenRun();
    });
  }

  return {
    prepare, start, answer, save, remove, discover, bindEvents,
    get searchQuery() { return searchQuery; },
    get filter() { return filter; },
  };
}
