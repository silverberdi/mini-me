const readTheme = () => {
  try { return localStorage.getItem("minime_theme"); } catch (_) { return null; }
};
const writeTheme = (value) => {
  try { localStorage.setItem("minime_theme", value); } catch (_) { /* in-memory theme remains usable */ }
};

export function createThemeController(button, icon) {
  const updateIcon = (theme) => {
    if (icon) icon.textContent = theme === "theme-light" ? "🌙" : "☀️";
  };
  const setTheme = (theme, persist = false) => {
    document.body.classList.remove("theme-dark", "theme-light");
    document.body.classList.add(theme);
    if (persist) writeTheme(theme);
    updateIcon(theme);
  };
  const initialize = () => {
    const saved = readTheme();
    const preferred = saved || (window.matchMedia?.("(prefers-color-scheme: dark)").matches
      ? "theme-dark" : "theme-light");
    setTheme(["theme-dark", "theme-light"].includes(preferred) ? preferred : "theme-dark");
    button?.addEventListener("click", () => {
      const next = document.body.classList.contains("theme-dark") ? "theme-light" : "theme-dark";
      setTheme(next, true);
    });
  };
  return { initialize };
}
