export interface Project {
  project_id: string;
  name?: string;
  repo_path?: string;
  github_repo?: string;
  status?: string;
  active_run_id?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface OrchestrationRun {
  run_id: string;
  project_id: string;
  request_id?: string | null;
  change_name?: string | null;
  stage: string;
  status: string;
  created_at?: string;
  updated_at?: string;
  active_agent_id?: string | null;
  error_detail?: string | null;
  metadata?: Record<string, any>;
}

export interface RequestItem {
  request_id: string;
  project_id: string;
  issue_number?: number | null;
  title: string;
  status: string;
  created_at?: string;
  updated_at?: string;
}

export interface QuotaObservation {
  provider: string;
  state: 'AVAILABLE' | 'EXHAUSTED' | 'UNKNOWN';
  observed_at: string;
  source: string;
  remaining_percent?: number | null;
  balance?: number | null;
  currency?: string | null;
  reset_at?: string | null;
  window?: string | null;
  model_id?: string | null;
  sublabel?: string | null;
  stale?: boolean;
  reason?: string | null;
}

export interface UserSession {
  authenticated: boolean;
  user?: {
    email: string;
    name?: string;
    picture?: string;
  } | null;
}

export interface ApiResponse<T> {
  ok: boolean;
  status: number;
  data: T | null;
  error?: string;
  offline?: boolean;
  aborted?: boolean;
}
