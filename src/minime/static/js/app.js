import { AppState } from "./state/store.js";
import { api } from "./services/api_client.js";
import { setOfflineBanner } from "./components/offline_banner.js";
import { renderHeader } from "./components/header.js";
import { renderKpis } from "./components/kpi_grid.js";
import { renderAttention } from "./components/attention_banner.js";
import { renderRuns } from "./components/runs_table.js";
import { renderProviders } from "./components/provider_grid.js";
const intervals = [5, 10, 30];
export const state = new AppState({ overview: null, queue: [], scheduler: null, runs: [], refreshSeconds: 10, autoRefresh: true });
let timer;
export async function refreshTelemetry() {
  try {
    const authResp = await fetch('/api/v1/auth/me');
    if (authResp.ok) {
      const authData = await authResp.json();
      if (!authData.authenticated) {
        setOfflineBanner(false);
        return null;
      }
    }
    const [overview, queue, scheduler, runs, providers] = await Promise.all([
      api.overview(),
      api.queue(),
      api.scheduler(),
      api.runs(),
      api.providers(),
    ]);
    state.update({ overview, queue, scheduler, runs, providers, connected: true });
    setOfflineBanner(false);
    return overview;
  } catch (error) {
    if (error?.status === 401 || error?.message?.includes("401")) {
      setOfflineBanner(false);
      return null;
    }
    state.update({ connected: false, error });
    setOfflineBanner(true);
    return null;
  }
}
const escapeHtml = (value) => String(value ?? "").replace(/[&<>\"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
export function renderQueue(items = []) { const target = document.querySelector("#queueList"); if (!target) return; if (!items.length) { target.innerHTML = '<p class="table-empty">No candidates currently in the autonomous queue.</p>'; return; } target.innerHTML = items.map((item, index) => { const blocked = item.admission_eligible === false || item.is_blocked || item.status === "BLOCKED"; const score = item.total_score ?? item.priority_score ?? item.score ?? "—"; const aging = item.starvation_aging_bonus ?? item.aging_bonus ?? 0; const refusal = item.refusal_code || item.block_reason || "Eligible"; return `<details class="queue-explain" ${index === 0 ? "open" : ""}><summary><strong>#${index + 1}</strong> ${escapeHtml(item.change_name || item.name)} <span class="status-badge ${blocked ? "status-warning" : "status-success"}">${blocked ? "BLOCKED" : "READY"}</span> <span class="text-muted">score ${escapeHtml(score)}</span></summary><div>Base score: <b>${escapeHtml(item.base_score ?? "—")}</b> · Starvation aging: <b>+${escapeHtml(aging)}</b> · Total: <b>${escapeHtml(score)}</b><br>Dependencies: ${escapeHtml(item.dependency_state || item.dependencies || "None reported")}<br>Admission: <b>${escapeHtml(refusal)}</b></div></details>`; }).join(""); }
function renderTelemetry(value) {
  const overview = value.overview || {};
  const metrics = overview.system_status || {};
  const blocked = (value.queue || []).filter((item) => item.admission_eligible === false || item.is_blocked || item.status === "BLOCKED").length;
  const ready = Math.max(0, (value.queue || []).length - blocked);
  renderHeader(document.querySelector(".top-nav"), metrics);
  renderKpis(document.querySelector(".kpi-grid"), { ...metrics, ready_count: ready, blocked_count: blocked });
  renderAttention(document.querySelector("#attentionBanner"), overview.attention_items || []);
  renderQueue(value.queue);
  renderRuns(document.querySelector("#runsTableBody"), value.runs, "ALL");
  renderProviders(document.querySelector("#providerGrid"), value.providers);
}
state.subscribe(value => renderQueue(value.queue));
state.subscribe(renderTelemetry);
export function configurePolling(seconds = 10) { const safe = intervals.includes(Number(seconds)) ? Number(seconds) : 10; clearInterval(timer); state.update({ refreshSeconds: safe }); timer = setInterval(() => { if (!document.hidden && state.value.autoRefresh) refreshTelemetry(); }, safe * 1000); return refreshTelemetry(); }
export function initPwa() { document.querySelector("#refreshBtn")?.addEventListener("click", () => refreshTelemetry()); document.querySelector("#autoRefreshToggle")?.addEventListener("change", event => { state.update({ autoRefresh: event.target.checked }); if (event.target.checked) refreshTelemetry(); }); document.querySelector("#refreshIntervalSelect")?.addEventListener("change", event => configurePolling(event.target.value)); document.querySelectorAll("[data-scroll-to]").forEach(button => button.addEventListener("click", () => document.getElementById(button.dataset.scrollTo)?.scrollIntoView({ behavior: "smooth" }))); document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshTelemetry(); }); configurePolling(Number(document.querySelector("#refreshIntervalSelect")?.value || 10)); if ("serviceWorker" in navigator) navigator.serviceWorker.register("/static/sw.js").catch(() => {}); }
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initPwa); else initPwa();
