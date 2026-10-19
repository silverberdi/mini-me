import { initDashboard } from "./dashboard.js";

// One DOM-ready bootstrap; domain controllers own lifecycle and interaction listeners.
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
