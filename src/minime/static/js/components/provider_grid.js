export const PROVIDER_STATES = ["AVAILABLE", "UNAVAILABLE", "RATE_LIMITED"];
export function renderProviders(root, providers = []) {
  if (!root) return;
  root.innerHTML = providers.length ? providers.map((provider) => `<article class="provider-card"><strong>${provider.provider_id || provider.provider}</strong><span class="status-badge">${provider.status || "UNKNOWN"}</span><small>${provider.latency_ms ?? "—"} ms · ${provider.spend_usd ?? "—"} USD</small></article>`).join("") : '<p class="table-empty">Provider health is unavailable.</p>';
}
