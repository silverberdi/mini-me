import { Injectable, signal, computed, effect, OnDestroy } from "@angular/core";
import { ApiService } from "./api.service";
import { Project, OrchestrationRun, RequestItem, QuotaObservation } from "./models";

@Injectable({
  providedIn: "root"
})
export class RefreshService implements OnDestroy {
  private timer: any = null;
  private abortController: AbortController | null = null;
  private generation = 0;

  // Signals for state
  readonly interval = signal<string>("10"); // "manual", "5", "10", "30"
  readonly isConnected = signal<boolean>(true);
  readonly isRefreshing = signal<boolean>(false);
  readonly lastUpdated = signal<Date | null>(null);
  readonly stale = signal<boolean>(false);

  readonly selectedProjectId = signal<string | null>(null);
  readonly projects = signal<Project[]>([]);
  readonly runs = signal<OrchestrationRun[]>([]);
  readonly requests = signal<RequestItem[]>([]);
  readonly closedRequests = signal<RequestItem[]>([]);
  readonly quotas = signal<QuotaObservation[]>([]);
  readonly syncState = signal<'idle' | 'syncing' | 'error'>('idle');
  private events: EventSource | null = null;

  // Computed
  readonly activeProject = computed(() => {
    const list = this.projects();
    const selected = this.selectedProjectId();
    if (selected) {
      const found = list.find(p => p.project_id === selected);
      if (found) return found;
    }
    return list.find(p => p.status === "ACTIVE") || list[0] || ({ project_id: '', name: '', status: 'ACTIVE', local_path: '', github_repo: '' } as Project);
  });

  readonly humanRequiredRun = computed(() => {
    return this.runs().find(r => r.status === "HUMAN_REQUIRED" || (r as any).human_gate === "HUMAN_REQUIRED" || !!r.metadata?.['human_payload']) || null;
  });

  constructor(private api: ApiService) {
    window.addEventListener('online', this.onOnline);
    window.addEventListener('offline', this.onOffline);
    effect(() => {
      const sec = this.interval();
      this.setupTimer(sec);
    });
    this.connectEvents();
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
    this.syncState.set('syncing');
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

      if (projRes.offline || runsRes.offline || (reqsRes?.offline ?? false)) {
        this.isConnected.set(false);
        this.stale.set(this.lastUpdated() !== null);
      } else {
        this.isConnected.set(true);
        this.stale.set(false);
      }

      if (projRes.ok && Array.isArray(projRes.data)) {
        this.projects.set(projRes.data);
      }

      if (runsRes.ok && Array.isArray(runsRes.data)) {
        this.runs.set(runsRes.data);
      }

      if (reqsRes && reqsRes.ok && Array.isArray(reqsRes.data)) {
        const payload: any = reqsRes.data;
        this.requests.set(Array.isArray(payload) ? payload : (payload.eligible_requests || payload.all_requests || []));
        if (payload && payload.closed_requests && Array.isArray(payload.closed_requests)) {
          this.closedRequests.set(payload.closed_requests);
        }
      }

      const quotaRes = await this.api.get<{providers: QuotaObservation[]}>("/api/v1/providers/quotas", { signal });
      if (quotaRes.ok && quotaRes.data?.providers) this.quotas.set(quotaRes.data.providers);

      if (!projRes.offline && !runsRes.offline) {
        this.lastUpdated.set(new Date());
        this.syncState.set('idle');
      }
    } catch {
      this.syncState.set('error');
      this.isConnected.set(false);
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
    this.events?.close();
  }

  private connectEvents(): void {
    if (typeof EventSource === 'undefined') return;
    this.events?.close();
    this.events = new EventSource('/api/v1/events');
    const refresh = () => void this.read();
    this.events.addEventListener('run.transition', refresh);
    this.events.addEventListener('run.accepted', refresh);
    this.events.addEventListener('run.failed', refresh);
    this.events.addEventListener('quota.update', (event: MessageEvent) => {
      try { this.quotas.set(JSON.parse(event.data).providers || []); } catch { /* polling repairs malformed events */ }
    });
    this.events.onerror = () => {
      // EventSource reconnects itself; polling remains the bounded fallback.
      this.isConnected.set(false);
    };
  }

  private onOnline = () => {
    void this.read();
  };

  private onOffline = () => {
    this.isConnected.set(false);
    this.stale.set(this.lastUpdated() !== null);
  };

  ngOnDestroy(): void {
    this.stop();
    window.removeEventListener('online', this.onOnline);
    window.removeEventListener('offline', this.onOffline);
  }
}
