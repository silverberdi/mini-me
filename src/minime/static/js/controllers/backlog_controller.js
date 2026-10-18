import { renderBacklogDetail, renderBacklogTable } from "../views/backlog_view.js";

/** Owns Backlog reads, selection, mutations, form state, and its listeners. */
export function createBacklogController({ fetchRequest, notify, getProjectId, refreshProjects, onUnauthorized, onStarted, confirmAction, workItemForm, elements, escapeHtml, sanitizeUrl, getStatusBadgeClass, onOpenRun }) {
  let searchQuery = '';
  let filter = 'ALL';
  let bound = false;
  let editingItemKey = null;
  let items = [];
  let selectedItem = null;
  let loadSequence = 0;
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
      await load(projectId);
      selectItem(itemKey);
      return result;
    } catch (error) { notify(`No se pudieron preparar los artefactos: ${error.message}`, 'error'); return null; }
  }

  async function start(itemKey) {
    const projectId = getProjectId();
    try {
      const result = await request(`/api/v1/projects/${encodeURIComponent(projectId)}/backlog/${encodeURIComponent(itemKey)}/start`, { method: 'POST' });
      notify(`Trabajo admitido. Run: ${result.run_id}`, 'success');
      await load(projectId);
      selectItem(itemKey);
      onStarted();
      return result;
    } catch (error) { notify(`No se pudo iniciar el trabajo: ${error.message}`, 'error'); return null; }
  }

  async function answer(itemKey, question, answerText) {
    const normalizedQuestion = String(question || "").trim();
    const normalizedAnswer = String(answerText || "").trim();
    if (!normalizedQuestion || !normalizedAnswer) return false;
    const projectId = getProjectId();
    try {
      await request(`/api/v1/projects/${encodeURIComponent(projectId)}/backlog/${encodeURIComponent(itemKey)}/answer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: normalizedQuestion, answer: normalizedAnswer }),
      }, 'Aclaración registrada; se volverá a evaluar la preparación.');
      await load(projectId);
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
    await load(projectId);
    selectItem(itemKey);
    return result;
  }

  async function remove(itemKey) {
    if (!confirmAction(`¿Eliminar el elemento ${itemKey}?`)) return false;
    const projectId = getProjectId();
    try {
      await request(`/api/v1/projects/${encodeURIComponent(projectId)}/backlog/${encodeURIComponent(itemKey)}`, { method: 'DELETE' });
      notify(`Trabajo ${itemKey} eliminado.`, 'info');
      selectedItem = null;
      await load(projectId);
      return true;
    } catch (error) { notify(`No se pudo eliminar el trabajo: ${error.message}`, 'error'); return false; }
  }

  async function discover(projectId = getProjectId()) {
    try {
      const result = await request(`/api/v1/projects/${encodeURIComponent(projectId)}/context/discover`, { method: 'POST' });
      notify(`Exploración completada. Elementos encontrados: ${result.discovered_items_count}`, 'success');
      await refreshProjects();
      await load(projectId);
      return result;
    } catch (error) { notify(`No se pudo explorar el contexto: ${error.message}`, 'error'); return null; }
  }

  function updateAdmissionPolicy(project) {
    const renderBoolean = (element, label, value) => {
      if (!element) return;
      const known = typeof value === 'boolean';
      element.textContent = `${label}: ${known ? (value ? 'ACTIVADA' : 'DESACTIVADA') : 'DESCONOCIDO'}`;
      element.dataset.state = known ? 'KNOWN' : 'UNKNOWN';
      element.className = `badge ${known && value ? 'badge-info' : 'badge-muted'}`;
    };
    renderBoolean(elements.autoPrepare, 'Preparación automática', project?.auto_prepare);
    renderBoolean(elements.autoAdmit, 'Admisión automática', project?.auto_admit);
    const limit = project?.max_concurrent_jobs;
    const knownLimit = Number.isInteger(limit) && limit > 0;
    if (elements.concurrency) {
      elements.concurrency.textContent = `Concurrencia: ${knownLimit ? limit : 'DESCONOCIDO'}`;
      elements.concurrency.dataset.state = knownLimit ? 'KNOWN' : 'UNKNOWN';
      elements.concurrency.className = 'badge badge-muted';
    }
  }

  function markdown(text) {
    if (!text) return '';
    return escapeHtml(text)
      .replace(/^### (.*$)/gim, '<h5>$1</h5>')
      .replace(/^## (.*$)/gim, '<h4>$1</h4>')
      .replace(/^# (.*$)/gim, '<h3>$1</h3>')
      .replace(/\*\*(.*?)\*\*/gim, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/gim, '<em>$1</em>')
      .replace(/`([^`]+)`/gim, '<code>$1</code>')
      .replace(/\n/gim, '<br>');
  }

  function renderTable() {
    renderBacklogTable({ root: elements.tableBody, items, filter, query: searchQuery, selectedItem, escapeHtml, getStatusBadgeClass });
  }

  function renderSelectedItem(item) {
    renderBacklogDetail({
      item,
      elements: elements.detail,
      escapeHtml,
      sanitizeUrl,
      renderMarkdownText: markdown,
      getStatusBadgeClass,
    });
  }

  function selectItem(itemKey) {
    const item = items.find((entry) => entry.item_key === itemKey);
    if (!item) return;
    selectedItem = item;
    elements.tableBody?.querySelectorAll('tr[data-item-key]').forEach((row) => {
      row.classList.toggle('selected-row', row.getAttribute('data-item-key') === itemKey);
    });
    renderSelectedItem(item);
  }

  function renderUnavailable() {
    items = [];
    selectedItem = null;
    updateAdmissionPolicy(null);
    if (elements.tableBody) elements.tableBody.innerHTML = '<tr><td colspan="6" class="table-empty">Selecciona un proyecto autorizado para consultar su trabajo.</td></tr>';
    if (elements.placeholder) {
      elements.placeholder.style.display = 'block';
      elements.placeholder.textContent = 'Selecciona un proyecto autorizado o registra uno desde Proyectos.';
    }
    if (elements.detail?.content) elements.detail.content.style.display = 'none';
  }

  function clear() {
    loadSequence += 1;
    items = [];
    selectedItem = null;
    renderUnavailable();
  }

  async function load(projectId = getProjectId()) {
    const sequence = ++loadSequence;
    if (!projectId) {
      renderUnavailable();
      return;
    }
    updateAdmissionPolicy(null);
    try {
      try {
        const projectResponse = await fetchRequest(`/api/v1/projects/${encodeURIComponent(projectId)}`);
        if (projectResponse.ok) {
          const project = await projectResponse.json();
          if (sequence === loadSequence && getProjectId() === projectId) updateAdmissionPolicy(project);
        }
      } catch { /* Admission facts are independently unavailable; backlog read may continue. */ }
      const response = await fetchRequest(`/api/v1/projects/${encodeURIComponent(projectId)}/backlog`);
      if ([401, 403].includes(response.status)) {
        if (sequence === loadSequence) onUnauthorized();
        return;
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const nextItems = await response.json();
      if (sequence !== loadSequence || getProjectId() !== projectId) return;
      items = nextItems;
      renderTable();
      if (selectedItem && items.some((item) => item.item_key === selectedItem.item_key)) {
        selectItem(selectedItem.item_key);
      } else if (items.length) {
        selectItem(items[0].item_key);
      } else {
        selectedItem = null;
        if (elements.placeholder) elements.placeholder.style.display = 'flex';
        if (elements.detail?.content) elements.detail.content.style.display = 'none';
      }
    } catch (error) {
      if (sequence === loadSequence) console.error('Failed fetching backlog:', error);
    }
  }

  function openEditor(itemToEdit = null) {
    const form = workItemForm;
    if (!form?.modal) return;
    editingItemKey = itemToEdit?.item_key || null;
    if (itemToEdit) {
      if (form.title) form.title.textContent = 'Editar trabajo';
      if (form.itemTitle) form.itemTitle.value = itemToEdit.title || '';
      if (form.itemKey) {
        form.itemKey.value = itemToEdit.item_key || '';
        form.itemKey.disabled = true;
      }
      if (form.priority) form.priority.value = itemToEdit.priority || 'NORMAL';
      if (form.description) form.description.value = itemToEdit.description || '';
      if (form.criteria) form.criteria.value = (itemToEdit.acceptance_criteria || []).join('\n');
    } else {
      if (form.title) form.title.textContent = 'Crear trabajo';
      form.form?.reset();
      if (form.itemKey) form.itemKey.disabled = false;
    }
    form.modal.showModal();
  }

  async function saveForm() {
    const form = workItemForm;
    const title = form?.itemTitle?.value.trim();
    const itemKey = form?.itemKey?.value.trim();
    const priority = form?.priority?.value || 'NORMAL';
    const description = form?.description?.value.trim() || '';
    const criteriaRaw = form?.criteria?.value.trim() || '';
    const acceptanceCriteria = criteriaRaw.split('\n')
      .map((criterion) => criterion.replace(/^[-*•]\s*/, '').trim())
      .filter(Boolean);
    if (!title) {
      notify('El título es obligatorio.', 'warning');
      return null;
    }
    try {
      const result = await save({
        item_key: itemKey || undefined,
        title,
        priority,
        description,
        acceptance_criteria: acceptanceCriteria,
      }, editingItemKey);
      form?.modal?.close();
      return result;
    } catch (error) {
      notify(`No se pudo guardar el trabajo: ${error.message}`, 'error');
      return null;
    }
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
    answerTarget,
    runArtifact,
    clearAnswer,
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
      const item = selectedItem;
      if (item) void prepare(item.item_key);
    });
    startButton?.addEventListener('click', () => {
      const item = selectedItem;
      if (item) void start(item.item_key);
    });
    editButton?.addEventListener('click', () => {
      const item = selectedItem;
      if (item) openEditor(item);
    });
    deleteButton?.addEventListener('click', async () => {
      const item = selectedItem;
      if (item) await remove(item.item_key);
    });
    answerForm?.addEventListener('submit', async (event) => {
      event.preventDefault();
      const item = selectedItem;
      const answerText = answerInput?.value.trim();
      const question = answerTarget?.value.trim() || item?.human_questions?.[0];
      if (item && question && answerText && await answer(item.item_key, question, answerText)) clearAnswer();
    });
    runArtifact?.addEventListener('click', (event) => {
      if (event.target.closest('[data-open-run]')) onOpenRun();
    });
  }

  return {
    prepare, start, answer, save, remove, discover, bindEvents, openEditor, saveForm,
    load, clear, renderUnavailable, renderTable, selectItem,
    getSelectedItem() { return selectedItem; },
    get searchQuery() { return searchQuery; },
    get filter() { return filter; },
  };
}
