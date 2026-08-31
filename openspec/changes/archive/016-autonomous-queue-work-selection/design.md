# Design: Autonomous Queue + Work Selection

## Architectural Context

Stage 016 completes the operational transition of mini me from a system requiring manual invocation (`minime orchestrate start` or `minime run`) to an autonomous engine that discovers, evaluates, prioritizes, admits, and starts READY work from registered project backlogs.

```text
       GitHub Project #2 & Issues
                   │
                   ▼ (1. Work Discovery)
          WorkDiscoveryService
                   │
                   ▼ (2. Definition of Ready & Validation)
           ReadinessService
                   │
                   ▼ (3. Deterministic Prioritization)
         Roadmap + Priority + Aging
                   │
                   ▼ (4. Admission Control & Concurrency)
   Global / Project Limits + RUN/DRAIN/WAIT
                   │
                   ▼ (5. Atomic Transactional Admission)
           SchedulerService (DB Lock)
                   │
                   ▼ (6. Native Startup)
  OrchestrationService + WorktreeManager
                   │
                   ▼
  Candidate Worktree + Run/Job + Pipeline Started
```

---

## 1. Domain Entities & Data Model

### WorkQueueItem
Represents an in-flight or evaluated work item in the scheduler's view:
- `queue_item_id`: UUID
- `project_id`: str (e.g. `mini-me`)
- `change_name`: str (e.g. `016-autonomous-queue-work-selection`)
- `github_issue_number`: int
- `github_issue_title`: str
- `priority`: `QueuePriority` (`CRITICAL`, `HIGH`, `NORMAL`, `LOW`)
- `roadmap_stage`: int | None (e.g. 16)
- `dependencies`: list[str] (list of required change names / issue numbers)
- `readiness_state`: `ReadinessState` (`READY`, `NOT_READY`, `BLOCKED`)
- `unmet_readiness_reasons`: list[str]
- `blocked_reason`: str | None
- `admission_eligible`: bool
- `discovered_at`: datetime (UTC)
- `last_evaluated_at`: datetime (UTC)

### SchedulerDecisionRecord
Immutable audit record of every scheduler admission evaluation:
- `decision_id`: UUID
- `project_id`: str
- `change_name`: str
- `github_issue_number`: int | None
- `decision`: `AdmissionDecision` (`ADMITTED`, `REFUSED`, `SKIPPED`)
- `reason_code`: `AdmissionRefusalCode` | None
- `reason_summary`: str
- `priority_score`: float
- `selected_implementer`: str | None
- `concurrency_snapshot`: dict[str, Any] (e.g. `{"global_active": 0, "project_active": 0}`)
- `capacity_snapshot`: dict[str, Any] (e.g. `{"mode": "RUN", "codex": "AVAILABLE", "antigravity": "AVAILABLE"}`)
- `run_id`: str | None (populated when `ADMITTED`)
- `evaluated_at`: datetime (UTC)

### Database Schema (PostgreSQL via Alembic `014_autonomous_queue_work_selection.py`)
- `work_queue_snapshots`: Persists current discovery & queue projection.
- `scheduler_decision_records`: Immutable append-only audit trail with indexes on `project_id`, `change_name`, `decision`, `reason_code`, and `evaluated_at`.

---

## 2. Work Discovery Service (`WorkDiscoveryService`)

1. **Source of Truth**:
   - Queries GitHub Project #2 items via `GitHubAdapter` (or `gh` CLI / GitHub API).
   - Matches items against registered projects in `uow.projects` by repository name (`owner/repo`).
   - Parses issue title / labels / metadata to extract linked OpenSpec change names.
2. **Durable Binding Reconciliation**:
   - If binding does not exist in `uow.bindings`, creates durable binding if the change directory exists in `openspec_path`.
   - If binding exists, ensures issue number and status are consistent.
3. **Idempotency & Filtering**:
   - Skips items not belonging to registered projects.
   - Skips closed/archived issues unless explicitly marked for re-evaluation.
   - Re-discovery is completely safe to run repeatedly; does not mutate immutable history.

---

## 3. Prioritization Algorithm & Roadmap Governance

Prioritization is strictly deterministic, transparent, and explainable. No LLM heuristics are used for scheduling authority.

### Priority Ranking Formula
For each candidate change $i$:

$$\text{Score}(i) = \text{BaseScore}(\text{Priority}_i) + \text{AgingBonus}(i) - \text{RoadmapPenalty}(i)$$

Where:
- $\text{BaseScore}(\text{Priority})$:
  - `CRITICAL` = 10,000
  - `HIGH` = 5,000
  - `NORMAL` = 1,000
  - `LOW` = 100
- $\text{AgingBonus}(i)$:
  - $\min(2,000, \text{age\_in\_hours}(i) \times 50)$ (prevents low-priority starvation while preserving order).
- $\text{RoadmapPenalty}(i)$:
  - Canonical roadmap stages (e.g. 001..016..018) enforce strict linear or declared dependency ordering.
  - If a predecessor roadmap stage $P < N$ is incomplete, stage $N$ receives $\text{RefusalCode} = \text{ROADMAP_PREDECESSOR_INCOMPLETE}$ and is **ineligible for admission**.

### Dependency Resolution
- Explicit dependencies listed in change metadata or binding must be in status `DONE` / `ARCHIVED`.
- If an incomplete dependency exists, item is refused with `DEPENDENCY_BLOCKED`.
- Cycle detection via topological sort prevents infinite scheduling loops.

### Deterministic Tie-Breaking
When two items have identical scores:
1. Smaller `roadmap_stage` first.
2. Earlier `discovered_at` first.
3. Lower `github_issue_number` first.

---

## 4. Admission Control & Concurrency Governance

Admission enforces hard operational constraints before starting execution:

1. **Definition of Ready (DoR)**:
   - Invokes `ReadinessService.evaluate_change_readiness`. If not `READY`, refusal code = `NOT_READY`.
2. **Capacity & Scheduler Mode**:
   - `RUN`: Allows new admissions.
   - `DRAIN`: Blocks new admissions (`PROVIDER_DRAIN`). Only in-flight runs advance.
   - `WAIT`: Blocks new admissions (`PROVIDER_WAIT`).
   - If required primary implementer is degraded/unavailable, blocks with `PROVIDER_UNAVAILABLE`.
3. **Concurrency Limits**:
   - `global_active_runs < max_global_jobs` (default 1). If exceeded: `GLOBAL_CONCURRENCY_LIMIT`.
   - `project_active_runs == 0` when `one_active_implementation_per_project` is true. If exceeded: `PROJECT_CONCURRENCY_LIMIT`.
   - `same_change_active == 0`. If active run exists for change: `CHANGE_ALREADY_ACTIVE`.
4. **Atomic Transactional Admission**:
   - Uses PostgreSQL transaction with explicit lock (`SELECT ... FOR UPDATE` or advisory lock) during the admission evaluation to prevent race conditions when multiple scheduler ticks run simultaneously.

---

## 5. Implementer Selection & Native Worktree Startup

When an item is admitted:
1. **Implementer Selection**:
   - Evaluates project configuration (`project.implementer`), provider health (`ProviderHealthService`), and model independence rules.
   - In standard mode, assigns primary implementer (`codex` or `antigravity`).
2. **Native Candidate Startup**:
   - Calls `OrchestrationService.admit_change(project_id, change_name)`, creating `OrchestrationRun` in stage `ADMITTED`.
   - Calls `WorktreeManager.create_isolated_worktree(project_id, change_name, base_sha)`, creating branch `minime/<change_name>-<uuid>` and isolated worktree.
   - Instantiates `Job` in status `QUEUED` / `RUNNING` with the selected implementer.
   - Spawns the orchestration coordinator loop to immediately begin execution.
3. **Self-Hosting Delivery Elimination**:
   - Completely removes manual worktree creation and manual run triggering by human or Antigravity!

---

## 6. Observability, TUI, and CLI

### CLI
- `minime scheduler tick [--project <id>]`: Executes a single atomic scheduler evaluation and admission cycle.
- `minime scheduler run [--interval <sec>]`: Long-running daemon loop.
- `minime scheduler status`: Displays current queue depth, scheduler mode, active runs, and capacity.
- `minime queue list`: Formatted table of current queue items, priorities, readiness, and blockers.
- `minime queue explain <change-name>`: Detailed explainability report showing exact ranking score and blocker breakdown.

### TUI Console
- Dedicated Queue View screen with:
  - Header: Mode (`RUN`/`DRAIN`/`WAIT`), Queue Depth, Ready Count, Blocked Count.
  - Ranked Candidates Table: Position, Project, Change, Priority, Status, Blocker Reason, Score.
  - Next-to-Admit Spotlight card.
  - Recent Admission Decisions audit feed.
  - Interactive Action: Trigger Tick (`t`), Refresh (`r`), Explain (`enter`).

---

## 7. Failure Isolation & Restart Safety

- **Failure Isolation**: An error or malformed spec in work item $A$ is captured in `SchedulerDecisionRecord` with `SPEC_INVALID` or `EVALUATION_ERROR` and does not prevent evaluation and admission of valid work item $B$.
- **Restart Safety**: On service start, `SchedulerService` reads persisted state from PostgreSQL (`OrchestrationRun`, `Job`, `ProjectBinding`), detects any active executions, reconciles queue state, and resumes without duplicating runs or worktrees.
