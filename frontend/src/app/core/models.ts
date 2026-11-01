export interface ProjectAgentProfile {
  agent_id: string;
  model_id: string;
  effort: string;
  workflows?: string[];
  skills?: string[];
}

export interface ProjectExecutionPolicy {
  max_review_rounds?: number;
  max_correction_attempts?: number;
  code_review_policy?: 'required' | 'risk_based' | 'disabled';
  fallback_authorized?: boolean;
}

export interface Project {
  project_id: string;
  display_name?: string;
  name?: string;
  project_type?: 'BROWNFIELD' | 'GREENFIELD';
  repo_path?: string;
  local_path?: string;
  github_repo?: string;
  repository?: string;
  base_branch?: string;
  status?: string;
  agent_profiles?: Record<string, ProjectAgentProfile>;
  execution_policy?: ProjectExecutionPolicy;
  provider_connections?: Record<string, any>;
  onboarding_status?: string;
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
  base_sha?: string | null;
  candidate_sha?: string | null;
  current_candidate_sha?: string | null;
  created_at?: string;
  updated_at?: string;
  is_active?: boolean;
  active_agent_id?: string | null;
  error_detail?: string | null;
  metadata?: Record<string, any>;
  human_gate?: string | null;
  stop_details?: Record<string, any> | null;
}

export interface RequestItem {
  request_id: string;
  project_id: string;
  issue_number?: number | null;
  title: string;
  body?: string | null;
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
