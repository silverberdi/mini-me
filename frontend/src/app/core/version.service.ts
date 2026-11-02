import { Injectable, signal } from "@angular/core";

export interface VersionInfo {
  version: string;
  commit_sha?: string;
  build_date?: string;
}

@Injectable({
  providedIn: "root"
})
export class VersionService {
  readonly info = signal<VersionInfo | null>(null);

  async load(): Promise<void> {
    try {
      const res = await fetch("/version.json", { cache: "no-store" });
      if (res.ok) {
        this.info.set((await res.json()) as VersionInfo);
      }
    } catch {
      // version is cosmetic; keep whatever we already have (or null)
    }
  }
}
