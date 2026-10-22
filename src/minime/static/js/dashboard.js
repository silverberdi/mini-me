/* F1 transition shell. F5 owns the replacement interactive UI. */

const authEndpoint = "/api/v1/auth/me";

function showReadOnlyTransition(operator) {
  const content = document.getElementById("authenticatedContent");
  const login = document.getElementById("loginSection");
  if (!content || !login) return;

  login.style.display = "none";
  content.style.display = "block";
  content.replaceChildren();

  const panel = document.createElement("section");
  panel.className = "panel";
  panel.setAttribute("aria-live", "polite");
  panel.innerHTML = `
    <h2>Observabilidad en transición</h2>
    <p>La cola, admisión, orquestación y panel operativo heredados fueron retirados en F1.</p>
    <p>La interfaz operativa será sustituida en F5. No se iniciará ningún trabajo desde esta pantalla.</p>
    <p class="text-muted">Operador: ${operator || "autorizado"}</p>
  `;
  content.append(panel);
}

export async function initDashboard() {
  try {
    const response = await fetch(authEndpoint, { credentials: "same-origin", cache: "no-store" });
    if (!response.ok) return;
    const payload = await response.json();
    if (payload.authenticated) showReadOnlyTransition(payload.operator?.email);
  } catch {
    // The login page remains visible when authentication is unavailable.
  }
}
