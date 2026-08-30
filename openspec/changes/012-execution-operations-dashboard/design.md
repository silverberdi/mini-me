# Design: Execution Operations Dashboard

## Architecture and Domain Projection

```text
+-----------------------------------------------------------------------------------+
|                            Operator Browser / Client                             |
|    - Overview Cards (State, Attention, Active, Completed)                         |
|    - Changes Master Table & Filters (Search, Status, Project)                    |
|    - Selected Change / Run Detail Panel                                          |
|      * 6-Phase Pipeline Stepper (Readiness -> Impl -> Checks -> Rev -> Audit -> PR)|
|      * Candidate Authority & Manifest Binding                                     |
|      * Deterministic Checks & Output Diagnostics                                  |
|      * Complementary Review Verdict & Findings                                    |
|      * DeepSeek Direct Audit & Risk Rating                                        |
|      * GitHub Issue / PR Binding                                                  |
|      * Chronological Event Transition Timeline                                    |
+-----------------------------------------------------------------------------------+
                                         |
                                         | HTTP GET (JSON / HTML / Static)
                                         v
+-----------------------------------------------------------------------------------+
|                               FastAPI Daemon                                      |
|    - GET / & /dashboard -> static HTML view                                       |
|    - /static/css/dashboard.css & /static/js/dashboard.js                         |
|    - GET /api/v1/dashboard/overview                                               |
|    - GET /api/v1/dashboard/changes/{project_id}/{change_name}                     |
|    - GET /api/v1/dashboard/runs/{run_id}                                          |
|    - GET /api/v1/dashboard/events                                                 |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                     OperationsDashboardService (Read Model)                       |
|    - Coordinates queries across UoW repositories with zero direct ad-hoc SQL      |
|    - Aggregates runs, jobs, checks, reviews, audits, blockers, events             |
|    - Evaluates 6-phase pipeline progress strictly from persisted durable facts     |
|    - Isolates stale historical review/audit evidence from current candidate       |
|    - Applies secret redaction to all diagnostics, messages, and event summaries   |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                        PostgreSQL Persistence Layer                               |
|    (projects, changes, orchestration_runs, jobs, attempts, check_results,        |
|     reviews, review_findings, audits, audit_findings, blocker_claims,             |
|     candidate_manifests, evidence_diagnostics, events, external_actions)          |
+-----------------------------------------------------------------------------------+
```

## Read Model Data Contracts

### 1. Overview DTO (`DashboardOverviewResponse`)
- `system_status`: Engine status, DB health, GitHub App health, scheduler mode (`RUN` | `DRAIN` | `WAIT`), active run count, queue depth.
- `attention_items`: List of runs currently in `NEEDS_HUMAN`, `WAITING_CAPACITY`, `RECOVERY_BLOCKED`, or failed check states with canonical reason, structured stop code, and retry/recovery viability.
- `active_executions`: List of currently executing runs with change name, project, stage, current executor, elapsed time, and latest progress.
- `recent_completions`: List of recently completed/merged runs with candidate SHA, PR number, review verdict, and audit risk.
- `changes`: Summary list of all discovered and registered changes with their latest operational status (`DISCOVERED`, `NOT_READY`, `READY`, `RUNNING`, `WAITING`, `NEEDS_HUMAN`, `COMPLETED`, `FAILED`).

### 2. Change / Run Detail DTO (`DashboardChangeDetailResponse`)
- `change_identity`: `project_id`, `change_name`, `status`, `target_branch`.
- `current_run`:
  - `run_id`, `status`, `stage`, `stop_outcome`, `human_gate`, `current_executor`, `generation`, `candidate_sha`, `base_sha`, `created_at`, `updated_at`.
- `pipeline`:
  - `readiness`: `state` (`PASSED`, `FAILED`, `BLOCKED`, `NOT_STARTED`), `details`.
  - `implementation`: `state` (`PASSED`, `RUNNING`, `FAILED`, `WAITING`, `NOT_STARTED`), `executor`, `attempts_count`, `latest_progress`, `is_mixed_authorship`.
  - `checks`: `state` (`PASSED`, `RUNNING`, `FAILED`, `NOT_STARTED`), `passed_count`, `failed_count`, `checks` (list of check name, exit code, duration ms, diagnostic snippet).
  - `review`: `state` (`PASSED`, `RUNNING`, `FAILED`, `NOT_STARTED`), `reviewer`, `verdict`, `material_findings_count`, `summary`, `is_stale_to_current_candidate`.
  - `audit`: `state` (`PASSED`, `RUNNING`, `FAILED`, `NOT_STARTED`), `provider`, `model`, `risk`, `material_findings_count`, `summary`, `is_stale_to_current_candidate`.
  - `pr_merge`: `state` (`PASSED`, `RUNNING`, `FAILED`, `NOT_STARTED`), `pr_number`, `pr_url`, `pr_state`, `is_merged`, `merge_commit_sha`.
- `candidate_authority`:
  - `current_generation`: Integer generation number.
  - `candidate_sha`: Full 40-char SHA (and short display SHA).
  - `base_sha`: Full 40-char base SHA.
  - `manifest_hash`: Hash of candidate manifest.
  - `changed_files`: List of modified/added files in manifest.
  - `is_frozen`: Boolean flag.
- `blocker_details`:
  - Active blocker claims, root causes, recovery blockers, capacity reset timestamps.
- `timeline`:
  - Chronological list of events (`timestamp`, `from_stage`, `to_stage`, `event_type`, `summary`, `details`).

## UI / UX Architecture

### Design Principles
1. **Desktop-First Operational Density**: Clean, compact grid and flexbox layout designed for operator observability without wasteful padding.
2. **Instant Scannability**: Semantic status badges with combined icon + text + high-contrast colors (e.g. green for passed/ready, amber for attention/waiting, red for failed/blocker, blue for running).
3. **Hierarchy**: Above-the-fold operational metrics -> Attention callout banner -> Filterable master table -> Drill-down detail drawer/card.
4. **Resilience & Zero CDN**: Pure self-contained CSS and vanilla JS; operates fully offline in containerized or local environments.
5. **Dark/Light Theme**: Accessible CSS custom properties with automatic system preference detection and manual toggle.

## Security & Secrets Scrubbing
All string fields emanating from command logs, audit summaries, review comments, and event payloads pass through `minime.logging.redact_secrets()` before being projected into the read model. API tokens, database connection strings, GitHub private keys, and environment passwords are fundamentally excluded from the API response schemas.
