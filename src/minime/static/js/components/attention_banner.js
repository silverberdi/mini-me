const escapeHtml = (value) => String(value ?? "").replace(/[&<>\"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
export function renderAttention(root, items = [], onSelect = () => {}) {
  if (!root) return;
  root.hidden = !items.length;
  root.style.display = items.length ? "block" : "none";
  if (!items.length) return;
  const list = root.querySelector("[data-attention-list], #attentionItemsContainer") || root;
  list.innerHTML = items.map((item) => `<button class="attention-item-card" type="button" data-run-id="${escapeHtml(item.run_id)}"><strong>${escapeHtml(item.change_name)}</strong><span>${escapeHtml(item.reason || item.human_gate || "Human action required")}</span></button>`).join("");
  list.querySelectorAll("[data-run-id]").forEach((button) => button.addEventListener("click", () => onSelect(button.dataset.runId)));
}
