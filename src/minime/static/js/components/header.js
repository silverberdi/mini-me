export function renderHeader(root, status = {}) {
  if (!root) return;
  const mode = status.scheduler_mode || status.mode || "RUN";
  root.dataset.schedulerMode = mode;
  const modeBadge = document.querySelector("#schedulerModeBadge");
  if (modeBadge) modeBadge.innerHTML = `<span class="dot dot-${mode === "RUN" ? "success" : mode === "DRAIN" ? "warning" : "muted"}"></span> MODE: ${mode}`;
  const db = document.querySelector("#dbHealthBadge");
  const healthy = status.database_healthy === true;
  const databaseState = healthy ? "Disponible"
    : status.database_healthy === false ? "No disponible" : "Desconocido";
  const databaseTone = healthy ? "success" : status.database_healthy === false ? "danger" : "muted";
  if (db) db.innerHTML = `<span class="dot dot-${databaseTone}"></span> Base de datos: ${databaseState}`;
}
