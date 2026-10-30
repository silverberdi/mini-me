import { Injectable, signal } from "@angular/core";

@Injectable({
  providedIn: "root"
})
export class ThemeService {
  readonly isDark = signal<boolean>(true);

  constructor() {
    const saved = localStorage.getItem("minime-theme");
    const isDark = saved !== "light";
    this.isDark.set(isDark);
    this.apply();
  }

  toggleTheme() {
    this.isDark.update(v => !v);
    localStorage.setItem("minime-theme", this.isDark() ? "dark" : "light");
    this.apply();
  }

  private apply() {
    if (this.isDark()) {
      document.documentElement.classList.add("dark");
      document.body.classList.remove("theme-light");
      document.body.classList.add("theme-dark");
    } else {
      document.documentElement.classList.remove("dark");
      document.body.classList.remove("theme-dark");
      document.body.classList.add("theme-light");
    }
  }
}
