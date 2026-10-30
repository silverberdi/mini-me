import { Injectable, signal, computed, effect } from "@angular/core";
import { ApiService } from "./api.service";
import { Project, OrchestrationRun, RequestItem } from "./models";

@Injectable({
  providedIn: "root"
})
export class RefreshService {
  private timer: any = null;
  private abortController: AbortController | null = null;
  private generation = 0;

  // Signals for state
  readonly interval = signal<string>("10"); // "manual", "5", "10", "30"
  readonly isConnected = signal<boolean>(true);
  readonly isRefreshing = signal<boolean>(false);
  readonly lastUpdated = signal<Date | null>(null);

  readonly selectedProjectId = signal<string | null>(null);
  readonly projects = signal<Project[]>([]);
  readonly runs = signal<OrchestrationRun[]>([]);
  readonly requests = signal<RequestItem[]>([]);

  // Computed
  readonly activeProject = computed(() => {
    const list = this.projects();
    const selected = this.selectedProjectId();
    if (selected) {
      const found = list.find(p => p.project_id === selected);
      if (found) return found;
    }
    return list.find(p => p.status === "ACTIVE") || list[0] || null;
  });

  constructor(private api: ApiService) {
    effect(() => {
      const sec = this.interval();
      this.setupTimer(sec);
    });
  }

  setInterval(val: string) {
    this.interval.set(val);
  }

  setSelectedProject(projectId: string) {
    this.selectedProjectId.set(projectId);
    void this.read();
  }

  setupTimer(secStr: string) {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
    if (secStr === "manual") return;
    const sec = parseInt(secStr, 10);
    if (!isNaN(sec) && sec > 0) {
      this.timer = setInterval(() => {
        void this.read();
      }, sec * 1000);
    }
  }

  async read(): Promise<void> {
    this.abortController?.abort();
    this.abortController = new AbortController();
    const signal = this.abortController.signal;
    const currentGen = ++this.generation;

    this.isRefreshing.set(true);
    const activeId = this.activeProject()?.project_id || this.selectedProjectId();
    const query = activeId ? `?project_id=${encodeURIComponent(activeId)}` : "";

    try {
      const [projRes, runsRes, reqsRes] = await Promise.all([
        this.api.get<Project[]>("/api/v1/projects", { signal }),
        this.api.get<OrchestrationRun[]>(`/api/v1/orchestration/runs${query}`, { signal }),
        activeId ? this.api.get<RequestItem[]>(`/api/v1/projects/${encodeURIComponent(activeId)}/requests`, { signal }) : Promise.resolve(null)
      ]);

      if (currentGen !== this.generation || projRes.aborted || runsRes.aborted) {
        return;
      }

      if (projRes.offline || runsRes.offline) {
        this.isConnected.set(false);
      } else {
        this.isConnected.set(true);
      }

      if (projRes.ok && Array.isArray(projRes.data)) {
        this.projects.set(projRes.data);
      }

      if (runsRes.ok && Array.isArray(runsRes.data)) {
        this.runs.set(runsRes.data);
      }

      if (reqsRes && reqsRes.ok && Array.isArray(reqsRes.data)) {
        this.requests.set(reqsRes.data);
      }

      this.lastUpdated.set(new Date());
    } finally {
      if (currentGen === this.generation) {
        this.isRefreshing.set(false);
      }
    }
  }

  stop() {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
    this.abortController?.abort();
  }
}
