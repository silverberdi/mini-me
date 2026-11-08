import { Injectable, signal, computed, OnDestroy } from "@angular/core";
import { ApiService } from "./api.service";
import { DashboardCost, Project, OrchestrationRun, RequestItem, QuotaObservation } from "./models";

@Injectable({
  providedIn: "root"
})
export class RefreshService implements OnDestroy {
  private abortController: AbortController | null = null;
  private generation = 0;
  private started = false;
  private lastDashboardFetchTime = 0;
  private readonly DASHBOARD_CACHE_TTL_MS = 300_000; // 5 minutes amortized cache

  // Signals for state
  readonly isConnected = signal<boolean>(true);
  readonly isRefreshing = signal<boolean>(false);
  readonly lastUpdated = signal<Date | null>(null);
  readonly stale = signal<boolean>(false);

  readonly selectedProjectId = signal<string | null>(null);
  readonly projects = signal<Project[]>([]);
  readonly runs = signal<OrchestrationRun[]>([]);
  readonly requests = signal<RequestItem[]>([]);
  readonly allRequests = signal<RequestItem[]>([]);
  readonly closedRequests = signal<RequestItem[]>([]);
  readonly quotas = signal<QuotaObservation[]>([]);
  readonly cost = signal<DashboardCost>({ status: 'no_data', providers: [], series: [] });
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
    return this.runs().find(r => r.is_active && (r.status === "HUMAN_REQUIRED" || (r as any).human_gate === "HUMAN_REQUIRED" || !!r.metadata?.['human_payload'] || !!(r as any).stop_details?.['human_payload'])) || null;
  });

  readonly projectProgressPercent = computed(() => {
    const closed = this.closedRequests().length;
    const open = this.requests().length;
    const total = closed + open;
    return total === 0 ? 0 : Math.round((closed / total) * 100);
  });

  readonly projectProgressSublabel = computed(() => {
    const closed = this.closedRequests().length;
    const open = this.requests().length;
    const total = closed + open;
    return total === 0 ? '0 solicitudes' : `${closed} de ${total} cerradas`;
  });

  constructor(private api: ApiService) {
    window.addEventListener('online', this.onOnline);
    window.addEventListener('offline', this.onOffline);
  }

  start(): void {
    if (this.started) return;
    this.started = true;
    this.connectEvents();
  }

  setSelectedProject(projectId: string): void {
    this.selectedProjectId.set(projectId);
    void this.read(true);
  }

  /**
   * Complete revalidation: used on app initialization, manual «Refrescar» button,
   * or when switching active projects.
   */
  async read(force = false): Promise<void> {
    this.abortController?.abort();
    this.abortController = new AbortController();
    const signal = this.abortController.signal;
    const currentGen = ++this.generation;

    this.isRefreshing.set(true);
    this.syncState.set('syncing');
    const activeId = this.activeProject()?.project_id || this.selectedProjectId();
    const query = activeId ? `?project_id=${encodeURIComponent(activeId)}` : "";

    const now = Date.now();
    const shouldFetchDashboard = force || (now - this.lastDashboardFetchTime >= this.DASHBOARD_CACHE_TTL_MS);

    try {
      const [projRes, runsRes, reqsRes, dashboardRes, quotaRes] = await Promise.all([
        this.api.get<Project[]>("/api/v1/projects", { signal }),
        this.api.get<OrchestrationRun[]>(`/api/v1/orchestration/runs${query}`, { signal }),
        activeId ? this.api.get<RequestItem[]>(`/api/v1/projects/${encodeURIComponent(activeId)}/requests`, { signal }) : Promise.resolve(null),
        shouldFetchDashboard
          ? this.api.get<{ cost: DashboardCost }>(`/api/v1/dashboard/overview${query}`, { signal })
          : Promise.resolve(null),
        this.api.get<{ providers: QuotaObservation[] }>("/api/v1/providers/quotas", { signal }),
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

      if (dashboardRes && dashboardRes.ok && dashboardRes.data?.cost) {
        this.cost.set(dashboardRes.data.cost);
        this.lastDashboardFetchTime = now;
      }

      if (reqsRes && reqsRes.ok && reqsRes.data) {
        this.applyRequestsPayload(reqsRes.data);
      }

      if (quotaRes.ok && quotaRes.data?.providers) {
        this.quotas.set(quotaRes.data.providers);
      }

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

  /**
   * Targeted update for runs and requests in response to SSE events.
   * Does NOT touch `projects` or `cost`, keeping configuration views completely undisturbed.
   */
  async refreshRuns(): Promise<void> {
    const activeId = this.activeProject()?.project_id || this.selectedProjectId();
    const query = activeId ? `?project_id=${encodeURIComponent(activeId)}` : "";

    try {
      const [runsRes, reqsRes] = await Promise.all([
        this.api.get<OrchestrationRun[]>(`/api/v1/orchestration/runs${query}`),
        activeId ? this.api.get<RequestItem[]>(`/api/v1/projects/${encodeURIComponent(activeId)}/requests`) : Promise.resolve(null),
      ]);

      if (runsRes.ok && Array.isArray(runsRes.data)) {
        this.runs.set(runsRes.data);
      }

      if (reqsRes && reqsRes.ok && reqsRes.data) {
        this.applyRequestsPayload(reqsRes.data);
      }
      this.lastUpdated.set(new Date());
      this.isConnected.set(true);
    } catch {
      // Background targeted refresh failure does not overwrite healthy state
    }
  }

  /**
   * Targeted update for projects list when a project lifecycle change event arrives.
   */
  async refreshProjects(): Promise<void> {
    try {
      const projRes = await this.api.get<Project[]>("/api/v1/projects");
      if (projRes.ok && Array.isArray(projRes.data)) {
        this.projects.set(projRes.data);
      }
      this.lastUpdated.set(new Date());
    } catch {
      // Ignored in background
    }
  }

  private applyRequestsPayload(payload: any): void {
    if (Array.isArray(payload)) {
      this.requests.set(payload);
      this.allRequests.set(payload);
    } else if (typeof payload === 'object') {
      const allRequests = Array.isArray(payload.all_requests) ? payload.all_requests : [];
      const eligibleRequests = Array.isArray(payload.eligible_requests)
        ? payload.eligible_requests
        : allRequests;
      this.requests.set(eligibleRequests);
      this.allRequests.set(allRequests.length > 0 ? allRequests : eligibleRequests);
      if (payload.closed_requests && Array.isArray(payload.closed_requests)) {
        this.closedRequests.set(payload.closed_requests);
      }
    }
  }

  stop(): void {
    this.abortController?.abort();
    this.events?.close();
    this.events = null;
  }

  private connectEvents(): void {
    if (typeof EventSource === 'undefined') return;
    this.events?.close();
    this.events = new EventSource('/api/v1/events');

    const handleRunEvent = () => void this.refreshRuns();
    const handleProjectEvent = () => void this.refreshProjects();

    this.events.addEventListener('run.transition', handleRunEvent);
    this.events.addEventListener('run.accepted', handleRunEvent);
    this.events.addEventListener('run.failed', handleRunEvent);
    this.events.addEventListener('run.gate_acknowledged', handleRunEvent);
    this.events.addEventListener('request.created', handleRunEvent);
    this.events.addEventListener('request.deactivated', handleRunEvent);
    this.events.addEventListener('request.reactivated', handleRunEvent);

    this.events.addEventListener('project.pause_changed', handleProjectEvent);

    this.events.addEventListener('quota.update', (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data);
        if (data.providers) this.quotas.set(data.providers);
      } catch {
        // Ignored
      }
    });

    this.events.onopen = () => {
      this.isConnected.set(true);
      this.stale.set(false);
    };

    this.events.onerror = () => {
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
