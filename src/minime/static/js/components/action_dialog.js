const escapeHtml = (value) => String(value ?? "").replace(/[&<>\"']/g, (character) => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  "\"": "&quot;",
  "'": "&#39;",
}[character]));

export function openConfirmModal({ title, description, warning, meta, onConfirm }) {
  const dialog = document.getElementById("actionDialog");
  if (!dialog || typeof onConfirm !== "function") return false;
  dialog.querySelector("[data-dialog-title]").textContent = title;
  dialog.querySelector("[data-dialog-description]").textContent = description;

  const warningBanner = document.getElementById("dialogWarningBanner");
  if (warningBanner) {
    warningBanner.textContent = warning ? `⚠️ ${warning}` : "";
    warningBanner.style.display = warning ? "block" : "none";
  }

  const metaBox = document.getElementById("dialogMetaInfo");
  if (metaBox) {
    const entries = meta && Object.keys(meta).length > 0 ? Object.entries(meta) : [];
    metaBox.innerHTML = entries.map(([key, value]) => `<div><strong>${escapeHtml(key)}:</strong> ${escapeHtml(value)}</div>`).join("");
    metaBox.style.display = entries.length ? "grid" : "none";
  }

  dialog.showModal();
  const confirmButton = document.getElementById("confirmActionBtn");
  if (!confirmButton) {
    dialog.close();
    return false;
  }
  confirmButton.onclick = () => {
    dialog.close();
    onConfirm();
  };
  dialog.querySelector("[data-cancel]").onclick = () => dialog.close();
  return true;
}

export function openParamModal({ title, description, fields, onSubmit }) {
  const dialog = document.getElementById("actionParamDialog");
  const body = document.getElementById("paramDialogBody");
  const titleNode = document.getElementById("paramDialogTitle");
  const submitButton = document.getElementById("submitParamActionBtn");
  if (!dialog || !body || !titleNode || !submitButton || typeof onSubmit !== "function") return false;

  titleNode.textContent = title;
  body.innerHTML = `
    <p class="dialog-desc">${escapeHtml(description)}</p>
    <form id="paramModalForm" class="param-form">
      ${fields.map((field) => {
        const label = escapeHtml(field.label);
        const id = `field_${escapeHtml(field.name)}`;
        if (field.type === "select") {
          return `<div class="form-group"><label for="${id}">${label}</label><select id="${id}" name="${escapeHtml(field.name)}" class="form-control">${field.options.map((option) => `<option value="${escapeHtml(option.value)}" ${option.value === field.default ? "selected" : ""}>${escapeHtml(option.label)}</option>`).join("")}</select></div>`;
        }
        if (field.type === "textarea") {
          return `<div class="form-group"><label for="${id}">${label}</label><textarea id="${id}" name="${escapeHtml(field.name)}" class="form-control" rows="3" placeholder="${escapeHtml(field.placeholder || "")}"></textarea></div>`;
        }
        return `<div class="form-group"><label for="${id}">${label}</label><input type="text" id="${id}" name="${escapeHtml(field.name)}" class="form-control" placeholder="${escapeHtml(field.placeholder || "")}" value="${escapeHtml(field.default || "")}"></div>`;
      }).join("")}
    </form>`;

  dialog.showModal();
  submitButton.onclick = (event) => {
    event.preventDefault();
    const form = document.getElementById("paramModalForm");
    if (!form) return;
    const values = Object.fromEntries(new FormData(form).entries());
    dialog.close();
    onSubmit(values);
  };
  dialog.querySelector("[data-param-cancel]").onclick = () => dialog.close();
  return true;
}
