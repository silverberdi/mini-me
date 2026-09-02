export const toast = message => window.dispatchEvent(new CustomEvent("minime:toast", { detail: String(message) }));
