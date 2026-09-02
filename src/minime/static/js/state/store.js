export class AppState extends EventTarget {
  constructor(initial = {}) { super(); this.value = { ...initial, connected: true }; }
  update(patch) { this.value = { ...this.value, ...patch }; this.dispatchEvent(new CustomEvent("change", { detail: this.value })); }
  subscribe(listener) { const fn = (event) => listener(event.detail); this.addEventListener("change", fn); listener(this.value); return () => this.removeEventListener("change", fn); }
}
