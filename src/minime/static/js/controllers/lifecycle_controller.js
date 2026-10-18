/** Owns browser lifecycle signals and the single authenticated refresh timer. */
export function createLifecycleController({
  windowRef = window,
  documentRef = document,
  refreshCurrentView,
  refreshAfterReconnect = refreshCurrentView,
  refreshOverview,
  setOfflineBanner,
  markFreshnessStale,
  onResize,
  refreshButton,
  refreshIntervalSelect,
  autoRefreshToggle,
  refreshTimer,
  storage = window.localStorage,
}) {
  const storageKey = 'minime_dashboard_interval';
  const allowedIntervals = new Set([5, 10, 30, 60]);
  let intervalSeconds = readInterval();
  let countdown = intervalSeconds;
  let timerId = null;
  let bound = false;

  function readInterval() {
    try {
      const value = Number.parseInt(storage?.getItem(storageKey) || '10', 10);
      return allowedIntervals.has(value) ? value : 10;
    } catch (_) {
      return 10;
    }
  }

  function writeInterval(value) {
    try { storage?.setItem(storageKey, String(value)); } catch (_) { /* storage is optional */ }
  }

  function resetCountdown() {
    countdown = intervalSeconds;
    if (refreshTimer) refreshTimer.textContent = `${countdown}s`;
  }

  function stop() {
    if (timerId !== null) windowRef.clearInterval(timerId);
    timerId = null;
  }

  function start() {
    stop();
    resetCountdown();
    if (autoRefreshToggle?.checked === false) {
      if (refreshTimer) refreshTimer.textContent = 'desactivada';
      return;
    }
    timerId = windowRef.setInterval(() => {
      if (autoRefreshToggle?.checked === false || documentRef.hidden) return;
      countdown -= 1;
      if (countdown <= 0) {
        resetCountdown();
        void refreshOverview();
      }
      if (refreshTimer) refreshTimer.textContent = `${countdown}s`;
    }, 1000);
  }

  function bind() {
    if (bound) return;
    bound = true;
    windowRef.addEventListener('resize', onResize, { passive: true });
    windowRef.addEventListener('offline', () => {
      setOfflineBanner(true);
      markFreshnessStale();
    });
    windowRef.addEventListener('online', () => {
      setOfflineBanner(false);
      void refreshAfterReconnect();
    });
    documentRef.addEventListener('visibilitychange', () => {
      if (!documentRef.hidden && autoRefreshToggle?.checked !== false) resetCountdown();
    });
    refreshButton?.addEventListener('click', () => {
      void refreshCurrentView();
      resetCountdown();
    });
    if (refreshIntervalSelect) {
      refreshIntervalSelect.value = String(intervalSeconds);
      refreshIntervalSelect.addEventListener('change', (event) => {
        const selected = Number.parseInt(event.target.value, 10);
        if (!allowedIntervals.has(selected)) {
          event.target.value = String(intervalSeconds);
          return;
        }
        intervalSeconds = selected;
        writeInterval(intervalSeconds);
        start();
      });
    }
    autoRefreshToggle?.addEventListener('change', () => {
      if (autoRefreshToggle.checked) start();
      else {
        stop();
        if (refreshTimer) refreshTimer.textContent = 'desactivada';
      }
    });
  }

  return { bind, start, stop, resetCountdown, get intervalSeconds() { return intervalSeconds; } };
}
