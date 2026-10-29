import { createApiClient } from "./client.js";
import { createRouter } from "./router.js";
import { createRefreshLifecycle } from "./refresh.js";
import { renderView } from "./views.js";

const state = { session: null, data: new Map(), context: {}, route: "/dashboard", generation: 0 };
const api = createApiClient({ state });
const refresh = createRefreshLifecycle({ api, state, onUpdate: render });
const router = createRouter({ onNavigate: ({ route, context }) => { state.route = route; state.context = context; render(); void refresh.read(); } });
const byId = (id) => document.getElementById(id);

function render() {
  if (!state.session?.authenticated) return;
  renderView({ root: byId("app"), route: state.route, state, api, navigate: router.navigate });
}

async function bootstrap() {
  document.body.classList.toggle("theme-light", localStorage.getItem("minime-theme") === "light");
  const session = await api.get("/api/v1/auth/me");
  if (!session.ok || !session.data?.authenticated) { byId("loginSection").hidden = false; document.querySelector(".app-layout").hidden = true; return; }
  state.session = session.data; byId("loginSection").hidden = true; document.querySelector(".app-layout").hidden = false;
  state.route = router.current().route; state.context = router.current().context;
  bindControls(); router.start(); render(); await refresh.read();
}

function bindControls() {
  byId("refreshNow")?.addEventListener("click", () => void refresh.read());
  byId("refreshInterval")?.addEventListener("change", (event) => refresh.setInterval(event.target.value));
  byId("themeToggle")?.addEventListener("click", (event) => { const light = document.body.classList.toggle("theme-light"); localStorage.setItem("minime-theme", light ? "light" : "dark"); event.currentTarget.textContent = light ? "Tema oscuro" : "Tema claro"; event.currentTarget.setAttribute("aria-pressed", String(light)); });
  byId("logoutButton")?.addEventListener("click", async () => { await api.post("/api/v1/auth/logout", {}); refresh.stop(); state.session = null; location.assign("/"); });
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => void bootstrap(), { once: true }); else void bootstrap();
