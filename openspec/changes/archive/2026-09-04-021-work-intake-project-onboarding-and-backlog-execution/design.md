# Design: 021 Work Intake, Project Onboarding, and Backlog Execution

## Architecture

```text
[ Authorized Operator ]
           |
      PWA Console (Desktop / Tablet / Mobile)
           |
      FastAPI API Boundary
           |
    +------+---------------------------------+
    |                                        |
[ ProjectOnboardingService ]        [ IntakeService ]
    |                                        |
    +-> [ ContextDiscoveryService ]          +-> [ OpenSpecGenerator ]
    |                                        +-> [ GitHubAdapter ] (Issues/Projects)
    +-> PostgreSQL (`projects`)              +-> [ ReadinessService ] (DoR)
    +-> PostgreSQL (`backlog_items`)         +-> [ SchedulerService ] (Admission)
```

## Data Model

### PostgreSQL Tables
1. `projects`:
   - `context_sources`: JSON array of relative paths (default: `["README.md", "docs/", "ROADMAP.md"]`)
   - `roadmap_path`: String(255) (default: `"docs/ROADMAP.md"`)
   - `backlog_path`: String(255) (default: `"docs/ROADMAP.md"`)
   - `github_project_number`: Integer (nullable)
   - `github_project_owner`: String(128) (nullable)
   - `onboarding_status`: String(32) (`UNBOUND`, `BINDING`, `CONTEXT_INCOMPLETE`, `READY_FOR_WORK`, `BLOCKED`)
   - `onboarding_reasons`: JSON array of strings

2. `backlog_items`:
   - `id`: String(64) PK
   - `project_id`: String(64) FK -> `projects.id`
   - `item_key`: String(128) (e.g., `021-work-intake`, `item-abc123`)
   - `title`: String(255)
   - `description`: Text
   - `priority`: String(32) (`CRITICAL`, `HIGH`, `NORMAL`, `LOW`)
   - `status`: String(32) (`BACKLOG`, `CONTEXT_CHECK`, `PREPARING`, `NEEDS_HUMAN`, `READY`, `ADMITTED`, `RUNNING`, `COMPLETED`, `BLOCKED`, `CANCELLED`)
   - `source`: String(32) (`ROADMAP`, `LOCAL_BACKLOG`, `GITHUB_ISSUE`, `MANUAL_INTAKE`, `OPENSPEC_CHANGE`)
   - `source_location`: String(255)
   - `dependencies`: JSON array of item keys
   - `readiness_state`: String(32) (`NOT_READY`, `NEEDS_HUMAN`, `READY`)
   - `unmet_readiness_reasons`: JSON array of strings
   - `human_questions`: JSON array of strings
   - `human_answers`: JSON array of objects (`{"question": "...", "answer": "...", "answered_at": "..."}`)
   - `acceptance_criteria`: JSON array of strings
   - `github_issue_number`: Integer (nullable)
   - `github_issue_url`: String(512) (nullable)
   - `github_project_item_id`: String(128) (nullable)
   - `openspec_change_name`: String(128) (nullable)
   - `run_id`: String(64) (nullable)
   - `created_at`: DateTime(timezone=True)
   - `updated_at`: DateTime(timezone=True)
   - Constraint: Unique `(project_id, item_key)`

## Key Flows

### 1. Project Onboarding Flow
1. Operator enters repository identity (e.g. `owner/repo` or path).
2. Service probes repository, verifies GitHub App permissions and repository existence.
3. Service inspects directory tree, discovering base branch, OpenSpec configuration, and context files.
4. Project record is created in PostgreSQL with evaluated `onboarding_status`.
5. Initial context discovery runs and populates initial backlog items.

### 2. Work Item Intake & Preparation Flow
1. Operator creates or selects a backlog item.
2. Operator triggers "Prepare".
3. `IntakeService` evaluates specification sufficiency.
   - If acceptance criteria or core intent is missing/ambiguous: sets `status = NEEDS_HUMAN` with specific human questions.
   - If sufficient: creates/syncs GitHub Issue, GitHub Project item, and OpenSpec change on disk (`proposal.md`, `specs/.../spec.md`, `tasks.md`).
4. `ReadinessService` evaluates Definition of Ready across all 11 criteria.
5. If DoR passes, item transitions to `READY`.

### 3. Execution Admission Flow
1. Operator clicks "Start Work".
2. `IntakeService` verifies `READY` status.
3. Service admits work item to `SchedulerService`, which creates `OrchestrationRun` + `Job` + worktree and begins normal SDLC pipeline (Codex -> Checks -> Complementary Review -> DeepSeek -> PR -> Merge Gate -> Post-Merge Closure).
4. Duplicate start requests return existing active Run idempotently without spawning duplicate jobs.
