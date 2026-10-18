const STORAGE_VERSION = 1;
const MIN_PANE_PX = 240;
const MAX_RATIO = 0.7;
const DESKTOP_QUERY = "(min-width: 1200px)";

async function operatorNamespace(email) {
  if (!email || !globalThis.crypto?.subtle) return null;
  const normalized = String(email).trim().toLocaleLowerCase("en-US");
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(normalized));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function boundedWidth(value, available) {
  const lower = MIN_PANE_PX;
  const upper = Math.min(available - MIN_PANE_PX, available * MAX_RATIO);
  if (!Number.isFinite(value) || upper < lower) return null;
  return Math.min(upper, Math.max(lower, value));
}

function paneSpace(grid) {
  // Reserve the 28px splitter and the two 12px CSS gaps before sizing panes.
  return Math.max(0, grid.clientWidth - 52);
}

export async function initDesktopPaneLayout(email) {
  const grid = document.querySelector(".content-split:not(.backlog-split)");
  const separator = document.getElementById("paneSeparator");
  const controls = document.querySelector(".pane-divider");
  const collapse = document.getElementById("collapseMasterPane");
  const reset = document.getElementById("resetPaneLayout");
  if (!grid || !separator || !controls || !collapse || !reset) return;

  const namespace = await operatorNamespace(email);
  const storageKey = namespace ? `minime:desktop-layout:v${STORAGE_VERSION}:${namespace}` : null;
  let preference = { version: STORAGE_VERSION, ratio: 0.42, collapsed: false };
  if (storageKey) {
    try {
      const stored = JSON.parse(localStorage.getItem(storageKey) || "null");
      if (stored?.version === STORAGE_VERSION && typeof stored.ratio === "number"
          && stored.ratio >= 0.3 && stored.ratio <= MAX_RATIO
          && typeof stored.collapsed === "boolean") preference = stored;
    } catch (_) {
      // Invalid or inaccessible preference falls back to a safe default.
    }
  }

  const desktop = window.matchMedia(DESKTOP_QUERY);
  const master = grid.querySelector(".master-panel");
  const apply = () => {
    const isDesktop = desktop.matches;
    grid.classList.toggle("master-collapsed", isDesktop && preference.collapsed);
    separator.hidden = !isDesktop || preference.collapsed;
    controls.hidden = !isDesktop;
    collapse.hidden = !isDesktop;
    reset.hidden = !isDesktop;
    collapse.textContent = preference.collapsed ? "Restaurar lista" : "Contraer lista";
    if (isDesktop && !preference.collapsed) {
      const available = paneSpace(grid);
      const width = boundedWidth(available * preference.ratio, available);
      if (width !== null) grid.style.setProperty("--master-pane-width", `${Math.round(width)}px`);
      separator.setAttribute("aria-valuemin", String(MIN_PANE_PX));
      separator.setAttribute("aria-valuemax", String(Math.round(Math.min(available - MIN_PANE_PX, available * MAX_RATIO))));
      separator.setAttribute("aria-valuenow", String(Math.round(width)));
      separator.setAttribute("aria-valuetext", `${Math.round(width)} px`);
    } else {
      grid.style.removeProperty("--master-pane-width");
    }
  };
  const persist = () => {
    if (!storageKey) return;
    try { localStorage.setItem(storageKey, JSON.stringify(preference)); } catch (_) { /* in-memory still works */ }
  };
  let pointerStart = null;
  separator.addEventListener("pointerdown", (event) => {
    if (!desktop.matches || preference.collapsed) return;
    pointerStart = { x: event.clientX, width: master.getBoundingClientRect().width };
    separator.setPointerCapture(event.pointerId);
  });
  separator.addEventListener("pointermove", (event) => {
    if (!pointerStart) return;
    const available = paneSpace(grid);
    const width = boundedWidth(pointerStart.width + event.clientX - pointerStart.x, available);
    if (width === null) return;
    preference.ratio = width / available;
    apply();
  });
  separator.addEventListener("pointerup", () => { if (pointerStart) persist(); pointerStart = null; });
  separator.addEventListener("pointercancel", () => { pointerStart = null; });
  separator.addEventListener("keydown", (event) => {
    if (!desktop.matches || preference.collapsed || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const available = paneSpace(grid);
    const current = boundedWidth(available * preference.ratio, available);
    const next = event.key === "Home" ? MIN_PANE_PX
      : event.key === "End" ? boundedWidth(available, available)
        : current + (event.key === "ArrowRight" ? 16 : -16);
    const width = boundedWidth(next, available);
    if (width !== null) { preference.ratio = width / available; apply(); persist(); }
  });
  collapse.addEventListener("click", () => { preference.collapsed = !preference.collapsed; apply(); persist(); });
  reset.addEventListener("click", () => {
    preference = { version: STORAGE_VERSION, ratio: 0.42, collapsed: false };
    if (storageKey) { try { localStorage.removeItem(storageKey); } catch (_) { /* safe default remains */ } }
    apply();
  });
  desktop.addEventListener?.("change", apply);
  window.addEventListener("resize", apply, { passive: true });
  apply();
}
