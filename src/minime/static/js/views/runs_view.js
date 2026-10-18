const escapeHtml = (value) => String(value ?? "").replace(/[&<>\"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
}[character]));

export function renderChangesView({ root, changes, filter, query, selected, alreadyAutoSelected, statusClass, formatTime, onSelect }) {
  if (!root || !Array.isArray(changes)) return alreadyAutoSelected;
  let visible = changes;
  if (filter === "ATTENTION") visible = visible.filter((change) => change.status === "NEEDS_HUMAN" || change.status === "WAITING");
  else if (filter === "RUNNING") visible = visible.filter((change) => change.status === "RUNNING");
  else if (filter === "READY") visible = visible.filter((change) => change.status === "READY");
  else if (filter === "COMPLETED") visible = visible.filter((change) => change.status === "COMPLETED");
  if (query) {
    const term = query.toLowerCase();
    visible = visible.filter((change) => [change.change_name, change.project_id, change.status]
      .some((value) => String(value || "").toLowerCase().includes(term)));
  }
  if (!visible.length) {
    root.innerHTML = '<tr><td colspan="6" class="table-empty">No hay cambios que coincidan con la búsqueda.</td></tr>';
    return alreadyAutoSelected;
  }
  root.innerHTML = visible.map((change) => {
    const isSelected = selected?.project_id === change.project_id && selected?.change_name === change.change_name;
    return `<tr class="${isSelected ? "selected" : ""}" data-project-id="${escapeHtml(change.project_id)}" data-change-name="${escapeHtml(change.change_name)}">
      <td><span class="badge ${statusClass(change.status)}">${escapeHtml(change.status)}</span></td>
      <td><strong>${escapeHtml(change.change_name)}</strong></td>
      <td>${escapeHtml(change.project_id)}</td>
      <td><span class="text-muted">${escapeHtml(change.stop_outcome || change.current_stage || "—")}</span></td>
      <td><code class="code-sha">${escapeHtml(change.candidate_sha_short || "—")}</code></td>
      <td class="text-muted">${escapeHtml(formatTime(change.updated_at))}</td>
    </tr>`;
  }).join("");

  if (!alreadyAutoSelected && !selected) {
    onSelect(visible[0].project_id, visible[0].change_name);
    return true;
  }
  return alreadyAutoSelected;
}
