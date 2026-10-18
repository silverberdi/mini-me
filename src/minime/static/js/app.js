import { initDashboard } from "./dashboard.js";

// One bootstrap owns initialization; dashboard.js owns refresh and listeners.
let initialized = false;
function bootstrap() {
  if (initialized) return;
  initialized = true;
  void initDashboard();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bootstrap, { once: true });
} else {
  bootstrap();
}
