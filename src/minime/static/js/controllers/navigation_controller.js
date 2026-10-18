/** Owns view navigation, execution selection, detail tabs, and their listeners. */
export function createNavigationController({
  documentRef = document,
  windowRef = window,
  mainNavTabs,
  bottomNavTabs,
  scrollButtons,
  mainViewPanes,
  detailTabs,
  tabPanes,
  changeSearchInput,
  filterPills,
  changesTableBody,
  attentionItemsContainer,
  copyShaButton,
  candidateShaNode,
  fetchBacklog,
  fetchProjects,
  fetchOverview,
  renderBacklogUnavailable,
  renderChangesTable,
  selectChange,
}) {
  let currentView = 'viewExecutions';
  let activeFilter = 'ALL';
  let searchQuery = '';
  let bound = false;

  function switchView(viewName) {
    currentView = viewName;
    documentRef.querySelectorAll('[data-main-view]').forEach((tab) => {
      const selected = tab.getAttribute('data-main-view') === viewName;
      tab.classList.toggle('active', selected);
      if (tab.hasAttribute('aria-selected')) tab.setAttribute('aria-selected', selected ? 'true' : 'false');
      if (tab.getAttribute('role') === 'tab') tab.tabIndex = selected ? 0 : -1;
      if (tab.hasAttribute('aria-current')) {
        if (selected) tab.setAttribute('aria-current', 'page');
        else tab.removeAttribute('aria-current');
      }
    });
    mainViewPanes.forEach((pane) => {
      const selected = pane.id === viewName;
      pane.style.display = selected
        ? (viewName === 'viewExecutions' && windowRef.matchMedia('(min-width: 1200px)').matches ? 'grid' : 'block')
        : 'none';
      pane.classList.toggle('active', selected);
    });
    if (viewName === 'viewBacklog') fetchBacklog();
    else if (viewName === 'viewProjects') fetchProjects();
    else if (viewName === 'viewExecutions') fetchOverview();
  }

  function bind() {
    if (bound) return;
    bound = true;
    mainNavTabs.forEach((tab) => {
      tab.tabIndex = tab.getAttribute('aria-selected') === 'true' ? 0 : -1;
      tab.addEventListener('keydown', (event) => {
        const tabs = Array.from(mainNavTabs);
        const current = tabs.indexOf(tab);
        const next = event.key === 'ArrowRight' ? (current + 1) % tabs.length
          : event.key === 'ArrowLeft' ? (current - 1 + tabs.length) % tabs.length
            : event.key === 'Home' ? 0
              : event.key === 'End' ? tabs.length - 1 : current;
        if (next === current) return;
        event.preventDefault();
        tabs[next].focus();
        tabs[next].click();
      });
    });
    mainNavTabs.forEach((tab) => tab.addEventListener('click', () => {
      const view = tab.getAttribute('data-main-view');
      if (view) switchView(view);
    }));
    bottomNavTabs.forEach((tab) => tab.addEventListener('click', () => {
      const view = tab.getAttribute('data-main-view');
      if (view) switchView(view);
    }));
    scrollButtons.forEach((button) => button.addEventListener('click', () => {
      switchView('viewExecutions');
      documentRef.getElementById(button.getAttribute('data-scroll-to'))?.scrollIntoView({
        behavior: windowRef.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
        block: 'start',
      });
    }));
    changeSearchInput?.addEventListener('input', (event) => {
      searchQuery = event.target.value.toLowerCase().trim();
      renderChangesTable();
    });
    filterPills.forEach((pill) => pill.addEventListener('click', () => {
      filterPills.forEach((entry) => entry.classList.remove('active'));
      pill.classList.add('active');
      activeFilter = pill.getAttribute('data-filter');
      renderChangesTable();
    }));
    detailTabs.forEach((tab) => tab.addEventListener('click', () => {
      detailTabs.forEach((entry) => {
        entry.classList.remove('active');
        entry.setAttribute('aria-selected', 'false');
        entry.tabIndex = -1;
      });
      tabPanes.forEach((pane) => pane.classList.remove('active'));
      tab.classList.add('active');
      tab.setAttribute('aria-selected', 'true');
      tab.tabIndex = 0;
      documentRef.getElementById(tab.getAttribute('data-tab'))?.classList.add('active');
    }));
    detailTabs.forEach((tab) => {
      tab.tabIndex = tab.getAttribute('aria-selected') === 'true' ? 0 : -1;
      tab.addEventListener('keydown', (event) => {
        const tabs = Array.from(detailTabs);
        const current = tabs.indexOf(tab);
        const next = event.key === 'ArrowRight' ? (current + 1) % tabs.length
          : event.key === 'ArrowLeft' ? (current - 1 + tabs.length) % tabs.length
            : event.key === 'Home' ? 0
              : event.key === 'End' ? tabs.length - 1 : current;
        if (next === current) return;
        event.preventDefault();
        tabs[next].focus();
        tabs[next].click();
      });
    });
    attentionItemsContainer?.addEventListener('click', (event) => {
      const card = event.target.closest('[data-project-id]');
      if (card) selectChange(card.getAttribute('data-project-id'), card.getAttribute('data-change-name'));
    });
    changesTableBody?.addEventListener('click', (event) => {
      const row = event.target.closest('[data-project-id]');
      if (row) selectChange(row.getAttribute('data-project-id'), row.getAttribute('data-change-name'));
    });
    changesTableBody?.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      const row = event.target.closest('tr[data-project-id]');
      if (!row) return;
      event.preventDefault();
      selectChange(row.dataset.projectId, row.dataset.changeName);
    });
    copyShaButton?.addEventListener('click', () => {
      if (!candidateShaNode || candidateShaNode.textContent === '---') return;
      navigator.clipboard.writeText(candidateShaNode.getAttribute('data-full-sha') || candidateShaNode.textContent);
      copyShaButton.textContent = '✓';
      windowRef.setTimeout(() => { copyShaButton.textContent = '📋'; }, 1500);
    });
  }

  return {
    bind,
    switchView,
    get currentView() { return currentView; },
    get activeFilter() { return activeFilter; },
    get searchQuery() { return searchQuery; },
  };
}
