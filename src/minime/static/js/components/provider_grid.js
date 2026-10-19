const escapeHtml = (value) => String(value ?? "").replace(/[&<>\"']/g, (character) => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  "\"": "&quot;",
  "'": "&#39;",
}[character]));

export function renderProviders(root, providers = []) {
  if (!root) return;
  if (!Array.isArray(providers)) {
    root.innerHTML = '<p class="table-empty">Disponibilidad de proveedores desconocida.</p>';
    return;
  }
  if (!providers.length) {
    root.innerHTML = '<p class="table-empty">No hay observaciones de proveedores disponibles.</p>';
    return;
  }
  root.innerHTML = providers.map((provider) => {
    const observedAt = provider.last_probe_at || provider.updated_at || "Hora no informada";
    return `<article class="provider-card">
      <strong>${escapeHtml(provider.provider || provider.provider_id || "Proveedor desconocido")}</strong>
      <span class="status-badge">${escapeHtml(provider.status || "UNKNOWN")}</span>
      <small>Modelo: ${escapeHtml(provider.model || "No informado")}</small>
      <small>Observado: ${escapeHtml(observedAt)}</small>
    </article>`;
  }).join("");
}
