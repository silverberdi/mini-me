# Design: Managed Repository Runtime Isolation

## Context and Architectural Laws

Stage C (`managed-repository-runtime-isolation`) is governed by the foundational architectural laws of mini me:

1. **One transition has one writer** (Stage A: `LifecycleTransitionAuthority`).
2. **Missing evidence never becomes success** (Stage B: `ExternalActionResult` fail-closed semantics).
3. **Projection/observation cannot resurrect terminal state**.
4. **External effects must be verifiable, idempotent, resumable**.
5. **Deployed runtime must never be the managed project workspace**.

Stage C focuses EXCLUSIVELY on Law 5 and its direct filesystem, repository, process isolation, and operational implications.

---

## Workspace Role Model Architecture

The system categorizes all filesystem paths into exactly four explicit workspace roles:

```python
class WorkspaceRole(str, Enum):
    RUNTIME = "RUNTIME"
    MANAGED_REPOSITORY = "MANAGED_REPOSITORY"
    EXECUTION_WORKTREE = "EXECUTION_WORKTREE"
    UNKNOWN = "UNKNOWN"
```

```
+-----------------------------------------------------------------------------------+
|                                  MINI ME HOST                                     |
|                                                                                   |
|  +-----------------------------------------------------------------------------+  |
|  | [RUNTIME] Runtime Checkout (e.g. /opt/minime/app)                           |  |
|  | - Running service binary & process code                                     |  |
|  | - STRICTLY READ-ONLY for all SDLC operations & executing agents             |  |
|  | - NEVER a managed workspace or worktree target                              |  |
|  +-----------------------------------------------------------------------------+  |
|                                                                                   |
|  +-----------------------------------------------------------------------------+  |
|  | TRUSTED MANAGED ROOT (e.g. /opt/minime/managed-projects)                    |  |
|  |                                                                             |  |
|  |  +-----------------------------------------------------------------------+  |  |
|  |  | MANAGED REPOSITORY ROOT (e.g. .../<project-id>/repository)             |  |  |
|  |  | - Canonical base checkout & Git history for project                     |  |  |
|  |  | - Hosts Project OpenSpec Workspace (openspec/specs/, changes/)          |  |  |
|  |  | - Mutations restricted to authorized canonical sync/fetch operations    |  |  |
|  |  +-----------------------------------------------------------------------+  |  |
|  |                                                                             |  |
|  |  +-----------------------------------------------------------------------+  |  |
|  |  | EXECUTION WORKTREES (e.g. .../<project-id>/worktrees/<run-id>)        |  |  |
|  |  | - Ephemeral isolated workspaces for jobs/runs/candidates               |  |  |
|  |  | - Carries OS/process-level write confinement boundary for agents        |  |  |
|  |  | - Agent code edits & review testing executed here ONLY                |  |  |
|  |  +-----------------------------------------------------------------------+  |  |
|  +-----------------------------------------------------------------------------+  |
+-----------------------------------------------------------------------------------+
```

### Role Taxonomy Definitions

1. **`RUNTIME`**:
   - The active, running deployment checkout of mini me (e.g. `/opt/minime/app` or local service checkout).
   - Treated as a **read-only deployment artifact** from the perspective of project SDLC management and agent processes.
   - Forbidden as an implementation target, worktree root, OpenSpec sync/archive destination, branch modification target, or agent writing workspace.

2. **`MANAGED_REPOSITORY`**:
   - The canonical base checkout and Git history repository for a registered project, residing under a configured trusted managed root (e.g. `/opt/minime/managed-projects/<project-id>/repository`).
   - Physically and logically distinct from `RUNTIME`.
   - Hosts canonical project Git refs, default base branch (`main`/`master`), and canonical Project OpenSpec artifacts.

3. **`EXECUTION_WORKTREE`**:
   - An ephemeral Git worktree or isolated workspace derived from `MANAGED_REPOSITORY` for a specific job, run, or change.
   - Resides strictly under `<managed-root>/<project-id>/worktrees/<worktree-id>`.
   - Bound to explicit job ownership metadata in durable DB storage and OS process write confinement for arbitrary-command agent subprocesses.
   - Agent code edits, pytest executions, auditor reviews, and candidate commits MUST happen strictly inside an `EXECUTION_WORKTREE`.

4. **`UNKNOWN`**:
   - Any path whose role cannot be authoritatively established or that lies outside trusted managed roots.
   - All mutations targeted at `UNKNOWN` paths fail closed (`EVIDENCE_INSUFFICIENT` / `POLICY_DENIED`).

### Logical Subspace: Project OpenSpec Workspace
- **Project OpenSpec Workspace** (`openspec/specs/`, `openspec/changes/`) is NOT an independent `WorkspaceRole`. It is a logical capability subtree located inside an authorized `MANAGED_REPOSITORY` or `EXECUTION_WORKTREE`.
- All OpenSpec operations (`new`, `apply`, `verify`, `sync`, `archive`) for a managed project MUST resolve against the project's `MANAGED_REPOSITORY` or `EXECUTION_WORKTREE`, NEVER against the `RUNTIME` checkout.

---

## Dual Control Model: ManagedWorkspaceGuard vs Process Write Confinement

The system separates application-level policy authorization from OS-level sub-process write confinement:

```
+-----------------------------------------------------------------------------------+
|                                 DUAL CONTROL MODEL                                |
|                                                                                   |
|  +-----------------------------------------------------------------------------+  |
|  | CONTROL 1: ManagedWorkspaceGuard (Policy Authority)                         |  |
|  | - Applies to ALL managed SDLC writers (internal services & agent runners)    |  |
|  | - Validates path canonicalization, trusted-root, role, & remote identity    |  |
|  +-----------------------------------------------------------------------------+  |
|                                        |                                          |
|                                        v                                          |
|  +-----------------------------------------------------------------------------+  |
|  | CONTROL 2: OS / Process Write Confinement (Enforcement Boundary)            |  |
|  | - Applied SPECIFICALLY to untrusted / agent-executed subprocesses             |  |
|  | - Restricts filesystem write syscalls strictly to assigned worktree path     |  |
|  | - Prevents sandbox escape attempts (cd /opt/minime/app, absolute path, etc)  |  |
|  +-----------------------------------------------------------------------------+  |
+-----------------------------------------------------------------------------------+
```

### 1. `ManagedWorkspaceGuard` (Application Policy Authority)
- **Scope**: ALL managed SDLC filesystem and Git writers across mini me MUST pass through `ManagedWorkspaceGuard` before executing a side effect.
- **Writers Covered**: `WorktreeManager`, orchestration setup, `OpenSpecSyncService`, `OpenSpecArchiveService`, Git branch/commit operations, post-merge cleanup, restart recovery, onboarding handlers, control-plane reconciliation, and self-hosting flows.
- **Responsibility**: Inspects project binding, canonicalizes paths (`os.path.realpath`), verifies trusted managed-root containment, rejects `..` path traversal and symlink escapes, verifies normalized Git remote identity, and checks role permissions.

### 2. OS / Process-Level Write Confinement (Execution Enforcement Boundary)
- **Scope**: Required SPECIFICALLY for untrusted or agent-executed subprocesses that can issue arbitrary shell commands or arbitrary filesystem operations.
- **Subprocesses Covered**:
  - Primary implementer agent processes.
  - Reviewer / auditor agent processes when capable of file writes.
  - Remediation and conflict-resolution agent processes.
  - Any future arbitrary-command execution agent runner.
- **Mechanism**: Enforced via OS sandboxing (e.g. `sandbox-exec` / seccomp / landlock), unprivileged execution identities, or container mount namespaces mounting `RUNTIME` and host paths read-only (`ro`) and only the assigned worktree read-write (`rw`).
- **Trusted Internal Writers**: Trusted internal service-side writers (e.g. `OpenSpecSyncService`, `WorktreeManager`) do NOT run inside an agent sandbox wrapper; they remain constrained by `ManagedWorkspaceGuard`, path canonicalization, and Stage B fail-closed postcondition verification.

---

## Pre-Creation Ordering & Worktree Ownership Protocol

In-tree marker files like `.minime-worktree.json` reside inside the worktree directory and are writable by executing agents. Therefore, an in-tree file MUST NOT be the sole authoritative evidence authorizing worktree creation, cleanup, or recovery.

### 1. Mandatory Pre-Creation Worktree Order
Before executing ANY filesystem or Git mutation that can create a worktree on disk (such as `git worktree add`), `WorktreeManager` MUST enforce the following exact sequence:

```
[1. Resolve + Authorize Path via Guard]
                 |
                 v
[2. Persist OrchestrationWorktreeOwnership in DB (creation_state = PENDING)]
                 |
                 v
[3. COMMIT & Durably Verify DB PENDING Record]  <--- If fails: STOP (No git worktree add)
                 |
                 v
[4. Execute git worktree add Mutation]
                 |
                 v
[5. Verify Filesystem / Git Postconditions]
                 |
                 v
[6. Transition DB Ownership to creation_state = CREATED]
```

#### Failure at Step 2 or 3
If persisting or committing the `PENDING` DB record fails:
- `WorktreeManager` MUST NOT execute `git worktree add`.
- The operation fails closed immediately with outcome `FAILURE` and reason_code `POSTCONDITION_NOT_PROVEN` or `DATABASE_ERROR`.
- No un-tracked directory or orphaned Git worktree is created on disk.

### 2. Four-Way Reconciliation for Cleanup & Deletion
`WorktreeManager` and post-merge cleanup tasks MUST execute 4-way reconciliation before deleting any worktree directory:
1. **Durable Ownership Record**: Query DB for `OrchestrationWorktreeOwnership` matching `canonical_worktree_path`, `project_id`, and `job_id`.
2. **Canonical Path Matching**: Verify actual resolved path on disk equals `durable_record.canonical_worktree_path`.
3. **Git Worktree Observation**: Execute `git worktree list` on `MANAGED_REPOSITORY` and verify Git authoritatively recognizes the worktree.
4. **In-Tree Marker (Corroborating)**: Inspect `.minime-worktree.json` if present. A marker corroborates ownership, but a marker ALONE without a matching DB record MUST NEVER authorize deletion.

If an agent spoofs or modifies `.minime-worktree.json`, the spoofed marker is rejected during DB reconciliation. Unowned, un-matched, or ambiguous directories MUST NOT be deleted automatically; they MUST return `UNKNOWN` / `EVIDENCE_INSUFFICIENT` and be preserved for operator review (`NEEDS_HUMAN`).

### 3. Fail-Closed Partial Worktree Recovery Protocol
To resolve partial worktree cleanup after a process crash during creation:
- **Authorized Recovery**: If a durable DB record exists with `creation_state = "PENDING"` (committed at Step 3 before crash), restart recovery authoritatively proves mini me initiated creation for that exact canonical path and `job_id`. Recovery MAY reconcile and prune the incomplete worktree directory safely after verifying path and repository identity against the DB record.
- **Forbidden Pruning**: If no durable DB record exists (`PENDING` or `CREATED`), or if DB ownership cannot be authoritatively established, the directory MUST NOT be deleted. Recovery returns `UNKNOWN` / `EVIDENCE_INSUFFICIENT` and preserves the directory for operator attention (`NEEDS_HUMAN`).

---

## Self-Hosting Isolation Principles

When mini me manages its own repository (`mini-me` managing `mini-me`):

1. `RUNTIME` (e.g. `/opt/minime/app`) and `MANAGED_REPOSITORY` (e.g. `/opt/minime/managed-projects/mini-me/repository`) **MUST remain two distinct filesystem and repository identities**.
2. **Identity Equality Fallacy**: Equality of repository URL (`github.com/silverberdi/mini-me`), project name (`mini-me`), commit SHA (`1f0d15...`), or working tree contents DOES NOT authorize using `RUNTIME` as a managed workspace.
3. Agents working on `mini-me` tasks write code inside `/opt/minime/managed-projects/mini-me/worktrees/<run-id>` under process write confinement, NEVER in `/opt/minime/app`.
4. OpenSpec sync and archive for `mini-me` changes update `/opt/minime/managed-projects/mini-me/repository`, NEVER `/opt/minime/app`.
5. Updating `/opt/minime/app` occurs ONLY via an explicit `DeploymentAuthority` flow.

---

## Project Managed Repository Binding & Remote Identity

Every managed project MUST have a persisted, verifiable binding that explicitly separates Git remote alias name from normalized repository identity:

```python
class ProjectManagedRepositoryBinding(BaseModel):
    project_id: str
    canonical_repository_identity: str  # Normalized repo identity, e.g. "github.com/org/repo"
    remote_name: str = "origin"          # Git remote alias name
    managed_repository_root: Path        # Absolute, canonicalized path
    worktree_parent_dir: Path            # Absolute, canonicalized path under managed root
    default_base_branch: str             # e.g. "main"
    ownership_marker_filename: str = ".minime-managed-project.json"
    created_at: datetime
    updated_at: datetime
```

### Git Remote Verification & Identity Normalization
When verifying Git repository remote identity:
1. The guard executes `git remote get-url <remote_name>` (using `binding.remote_name`).
2. The observed URL string is parsed and normalized to resolve protocol/format variations (e.g. `git@github.com:org/repo.git` and `https://github.com/org/repo.git` normalize to `github.com/org/repo`).
3. The normalized observed identity MUST match `binding.canonical_repository_identity`.
4. If parsing is unparseable or identity mismatches, verification returns `FAILURE` / `CONFLICT` or `UNKNOWN` / `UNOBSERVABLE` fail closed.

---

## Central `ManagedWorkspaceGuard` Architecture

All SDLC filesystem and Git side effects across mini me MUST pass through `ManagedWorkspaceGuard`:

```python
class WorkspaceMutationRequest(BaseModel):
    project_id: str
    target_path: Path
    requested_operation: WorkspaceOperation  # EDIT, WORKTREE_CREATE, WORKTREE_DELETE, GIT_BRANCH, GIT_COMMIT, OPENSPEC_SYNC, OPENSPEC_ARCHIVE
    job_id: str | None = None
    run_id: str | None = None

class WorkspaceMutationDecision(BaseModel):
    allowed: bool
    outcome: ExternalOutcome  # SUCCESS, FAILURE, UNKNOWN
    reason_code: ExternalReasonCode  # EXECUTION_SUCCESS, POLICY_DENIED, CONFLICT, EVIDENCE_INSUFFICIENT
    workspace_role: WorkspaceRole
    resolved_path: Path
    provider_detail: str | None = None
```

### Guard Verification Protocol
1. **Resolve Project Binding**: Fetch authoritative `ProjectManagedRepositoryBinding` for `project_id`.
2. **Path Canonicalization**: Resolve `target_path` using `os.path.realpath` / `Path.resolve()`.
3. **Runtime Protection Check**: Verify `resolved_path` does NOT overlap with `RUNTIME` (neither equal, prefix, nor parent).
4. **Trusted Root Verification**: Verify `resolved_path` is strictly contained inside `managed_repository_root` or `worktree_parent_dir`. Reject symlink escapes and path traversal (`..`).
5. **Role Classification**: Classify workspace role (`MANAGED_REPOSITORY` vs `EXECUTION_WORKTREE`). Reject `RUNTIME` or `UNKNOWN`.
6. **Git Remote Verification**: Execute `git remote get-url <remote_name>` on target repository and compare normalized identity to `canonical_repository_identity`.
7. **Operation Authorization**: Verify requested operation is permitted for the classified workspace role:
   - `RUNTIME`: ALL SDLC mutations DENIED (`POLICY_DENIED`).
   - `MANAGED_REPOSITORY`: Base branch fetch, canonical OpenSpec sync/archive, and worktree spawn ALLOWED. Code edits and candidate commits DENIED.
   - `EXECUTION_WORKTREE`: Agent code edits, test execution, candidate branch/commit ALLOWED.
8. **Return Typed Decision**: Return `WorkspaceMutationDecision` with fail-closed Stage B outcome semantics.

---

## Formalized Deployment Authority Boundary

`ManagedWorkspaceGuard` governs **MANAGED SDLC MUTATIONS**. SDLC callers (orchestration drivers, agent runners, OpenSpec sync/archive, branch cleanup tasks) can NEVER receive authority from `ManagedWorkspaceGuard` to mutate `RUNTIME`.

```
+-----------------------------------------------------------------------------------+
|                            AUTHORITY BOUNDARY SEPARATION                          |
|                                                                                   |
|  +-------------------------------------+   +-----------------------------------+  |
|  | ManagedWorkspaceGuard               |   | DeploymentAuthority               |  |
|  | - Governs SDLC mutations            |   | - Governs production deployment   |  |
|  | - RUNTIME mutations ALWAYS DENIED   |   | - Unidirectional promotion        |  |
|  | - SDLC callers cannot escalate      |   | - Separate explicit pipeline      |  |
|  +-------------------------------------+   +-----------------------------------+  |
+-----------------------------------------------------------------------------------+
```

### Boundary Rules
- SDLC callers MUST NOT impersonate, bypass, or escalate into `DeploymentAuthority`.
- `DeploymentAuthority` executes via an explicit, separate deployment pipeline (e.g. service container replacement, artifact extraction, systemd reload).
- Deployment MAY update `RUNTIME` files or binary state from a verified candidate commit SHA, but deployment NEVER grants `MANAGED_REPOSITORY` or `EXECUTION_WORKTREE` semantics to `RUNTIME`.
- `RUNTIME` remains strictly read-only for all SDLC operations before, during, and after deployment.

---

## Inventory of Covered Writers

All SDLC writers MUST pass through `ManagedWorkspaceGuard`, and arbitrary-command agent subprocesses MUST additionally execute under process write confinement:

1. **`WorktreeManager`**: Creation, setup, and deletion of Git worktrees (passes `ManagedWorkspaceGuard`; enforces pre-creation DB PENDING ordering).
2. **Orchestration Startup & Setup**: Worktree initialization and base checkout (passes `ManagedWorkspaceGuard`).
3. **Primary Implementer Execution**: Agent workspace resolution and file modification tools (passes `ManagedWorkspaceGuard` AND runs under OS process write confinement).
4. **Reviewer Execution**: Auditor checkout, test runner, and patch application (passes `ManagedWorkspaceGuard` AND runs under OS process write confinement when capable of writes).
5. **Remediation & Integration Worktrees**: Worktrees created for conflict resolution or candidate remediation (passes `ManagedWorkspaceGuard` AND runs under OS process write confinement for agent execution).
6. **`OpenSpecSyncService`**: Reading delta specs and writing canonical main specs in `openspec/specs/` (passes `ManagedWorkspaceGuard`).
7. **`OpenSpecArchiveService`**: Relocating completed change directories to `openspec/changes/archive/` (passes `ManagedWorkspaceGuard`).
8. **OpenSpec Change Authoring**: `openspec new` and change proposal updates (passes `ManagedWorkspaceGuard`).
9. **Git Branch Operations**: Creation, checkout, and deletion of local/remote branches (passes `ManagedWorkspaceGuard`).
10. **Git Commit & Push**: Authoring candidate commits and pushing to remotes (passes `ManagedWorkspaceGuard`).
11. **Post-Merge Cleanup**: Local branch deletion, worktree pruning, and archive verification (passes `ManagedWorkspaceGuard`; executes 4-way DB reconciliation).
12. **Restart Recovery**: Re-attaching to or cleaning up worktrees after process restart (passes `ManagedWorkspaceGuard`; requires durable DB PENDING/CREATED record for recovery).
13. **Control Plane / Manual Reconciliation**: Manual operator actions touching workspace files (passes `ManagedWorkspaceGuard`).
14. **Self-Hosting Workflows**: All SDLC operations when managing `mini-me` (passes `ManagedWorkspaceGuard` AND process write confinement for agents).
15. **Deployment Handoff Boundary**: Promotion artifact packaging (passes `ManagedWorkspaceGuard` for artifact creation; hands off to `DeploymentAuthority`).

---

## Observability & Telemetry

The system MUST expose the following workspace isolation telemetry:

- `project_id` and active `managed_repository_root` path.
- Current `managed_repository` HEAD SHA and verified `canonical_repository_identity`.
- Deployed `RUNTIME` path and active `RUNTIME` SHA.
- Isolation status boolean: `is_runtime_isolated` (True ONLY if `RUNTIME` and `MANAGED_REPOSITORY` paths do not overlap).
- Process write confinement status: `is_agent_confinement_active`.
- Active worktree list backed by durable `OrchestrationWorktreeOwnership` records.
- Metric counter: `workspace_mutation_denied_total` (labels: `project_id`, `reason_code`, `attempted_operation`).

---

## Failure Semantics (Stage B Integration)

Workspace identity and mutation guard decisions MUST map directly to Stage B typed outcome semantics:

| Failure Case | Outcome | Reason Code | Retry Safety | Action |
| :--- | :--- | :--- | :--- | :--- |
| Workspace identity unproven or missing | `UNKNOWN` | `EVIDENCE_INSUFFICIENT` | `UNSAFE` | Block execution; request binding |
| SDLC mutation requested against `RUNTIME` | `FAILURE` | `POLICY_DENIED` | `UNSAFE` | Block mutation; log security violation |
| Agent process write escape attempt | `FAILURE` | `POLICY_DENIED` | `UNSAFE` | Terminate process; deny write |
| DB PENDING persistence failure | `FAILURE` | `POSTCONDITION_NOT_PROVEN` | `UNSAFE` | Block worktree creation |
| Symlink escape / path traversal | `FAILURE` | `POLICY_DENIED` | `UNSAFE` | Block mutation; reject path |
| Git remote identity mismatch | `FAILURE` | `CONFLICT` | `UNSAFE` | Block mutation; reject repository |
| Unowned/ambiguous worktree cleanup | `UNKNOWN` | `EVIDENCE_INSUFFICIENT` | `UNSAFE` | Preserve folder; require human review |
| Filesystem I/O or stat error | `UNKNOWN` | `UNOBSERVABLE` | `SAFE` | Retry query; block mutation |

---

## Admission Fence Rules

Fresh work MUST NOT advance from `READY` to `IN_PROGRESS` if any of the following fence conditions hold:

1. `ProjectManagedRepositoryBinding` is missing or unpersisted for the target project.
2. `managed_repository_root` equals, contains, or is contained by `RUNTIME`.
3. `ManagedWorkspaceGuard` fails Git remote verification against `canonical_repository_identity`.
4. Workspace role classification yields `RUNTIME` or `UNKNOWN`.
5. OS process write confinement boundary cannot be verified for executing agent runners.
6. Creation of an `EXECUTION_WORKTREE` under the authorized managed root fails pre-creation DB `PENDING` persistence or postcondition verification.

---

## Required Invariants

- **Invariant 1**: `RUNTIME` path and `MANAGED_REPOSITORY` path MAY NEVER resolve to the same filesystem identity.
- **Invariant 2**: A mutating SDLC action against `RUNTIME` MUST ALWAYS be denied (`POLICY_DENIED`).
- **Invariant 3**: A workspace target outside the trusted managed root MUST ALWAYS be denied (`POLICY_DENIED`).
- **Invariant 4**: A managed path bound to a different `project_id` MUST ALWAYS be denied (`CONFLICT`).
- **Invariant 5**: A Git repository remote identity mismatch MUST ALWAYS block execution (`CONFLICT`).
- **Invariant 6**: Unknown workspace identity MUST ALWAYS block mutation (`EVIDENCE_INSUFFICIENT`).
- **Invariant 7**: OpenSpec sync and archive operations CANNOT run against `RUNTIME` paths.
- **Invariant 8**: Self-hosting `mini-me` MUST use a separate managed repository directory distinct from `RUNTIME`.
- **Invariant 9**: Worktree cleanup CANNOT delete an unowned, un-marked, or ambiguous directory lacking durable DB ownership proof.
- **Invariant 10**: `ManagedWorkspaceGuard` DENIES all SDLC mutations against `RUNTIME`; only an explicit, separate `DeploymentAuthority` MAY update `RUNTIME` from a verified artifact or commit SHA without granting managed-workspace semantics to `RUNTIME`.
- **Invariant 11**: An agent process executing in `EXECUTION_WORKTREE` MUST NOT be able to write `RUNTIME` or any path outside its assigned worktree, enforced at the OS/process level.
- **Invariant 12**: Durable `OrchestrationWorktreeOwnership` with `creation_state = PENDING` MUST be committed to DB before `git worktree add` or any creation mutation is executed.

---

## Adversarial Scenarios

The test plan MUST validate the following 21 adversarial scenarios:

1. **Scenario: `RUNTIME` == `MANAGED_REPOSITORY` Path Attempt**
   - Attempting to bind `managed_repository_root` to `/opt/minime/app` is rejected during onboarding/readiness with `FAILURE` / `POLICY_DENIED`.

2. **Scenario: `RUNTIME` as Parent of `MANAGED_REPOSITORY`**
   - Setting `managed_repository_root` to `/opt/minime/app/managed_repo` is rejected with `FAILURE` / `POLICY_DENIED`.

3. **Scenario: `MANAGED_REPOSITORY` as Parent of `RUNTIME`**
   - Setting `managed_repository_root` to `/opt/minime` (when runtime is `/opt/minime/app`) is rejected with `FAILURE` / `POLICY_DENIED`.

4. **Scenario: Symlink inside Managed Path Resolves into `RUNTIME`**
   - A symlink inside `managed-projects/mini-me/repository/src` pointing to `/opt/minime/app/src` is detected during path canonicalization and mutation is rejected with `FAILURE` / `POLICY_DENIED`.

5. **Scenario: Worktree Symlink Escapes Trusted Root**
   - A worktree creation request specifying a target path escaping `<managed-root>` via symlink or `../` is rejected with `FAILURE` / `POLICY_DENIED`.

6. **Scenario: Wrong Git Remote Identity**
   - A managed repository directory whose `git remote get-url origin` returns `git@github.com:attacker/fake-repo.git` instead of `binding.canonical_repository_identity` is rejected with `FAILURE` / `CONFLICT`.

7. **Scenario: Repo Copied from Correct Project but `.git` Points Elsewhere**
   - A repository folder with correct code files whose `.git` file or gitdir points to an external repository is rejected during remote verification with `FAILURE` / `CONFLICT`.

8. **Scenario: Stale Workspace Binding**
   - A project binding pointing to a deleted or unmounted filesystem path returns `UNKNOWN` / `EVIDENCE_INSUFFICIENT` and blocks admission.

9. **Scenario: Missing Managed Repository Directory**
   - When `managed_repository_root` does not exist on disk, fresh work admission is blocked with `UNKNOWN` / `EVIDENCE_INSUFFICIENT`.

10. **Scenario: Corrupt `.git` Directory in Managed Repo**
    - When `git rev-parse --show-toplevel` fails due to a corrupted `.git` folder, mutation is blocked with `UNKNOWN` / `UNOBSERVABLE`.

11. **Scenario: Inaccessible Filesystem / Permission Error**
    - When filesystem `stat` or `os.listdir` encounters `EPERM` / `EACCES`, the guard returns `UNKNOWN` / `UNOBSERVABLE` without assuming default success.

12. **Scenario: Existing Unmanaged Worktree with Matching Job-like Name**
    - A directory `worktrees/job-123` lacking a matching `OrchestrationWorktreeOwnership` record in DB is encountered during cleanup; cleanup skips deletion and returns `UNKNOWN` / `EVIDENCE_INSUFFICIENT`.

13. **Scenario: Same Repo URL Registered to Multiple Project IDs**
    - Registering `git@github.com:org/repo.git` under `project-A` and `project-B` enforces distinct managed repository roots (`managed-projects/project-A/repository` vs `managed-projects/project-B/repository`). Cross-project mutation is rejected with `FAILURE` / `CONFLICT`.

14. **Scenario: Self-Hosting `mini-me` Execution Isolation**
    - Executing a `mini-me` self-hosting task creates worktree in `/opt/minime/managed-projects/mini-me/worktrees/run-789`. File edits by implementer alter `run-789`, while `/opt/minime/app` remains 100% unchanged.

15. **Scenario: Partial Worktree Recovery with Pre-Creation DB Record**
    - Process crashes midway through `git worktree add`. Durable DB contains `OrchestrationWorktreeOwnership` record with `creation_state = "PENDING"`. Recovery verifies DB record, canonical path, and repository identity, then prunes partial worktree safely.

16. **Scenario: Partial Worktree Pruning Attempt Without DB Record**
    - An incomplete worktree directory exists on disk, but no `OrchestrationWorktreeOwnership` DB record exists. Recovery refuses deletion, returns `UNKNOWN` / `EVIDENCE_INSUFFICIENT`, and preserves directory for operator review.

17. **Scenario: Spoofed In-Tree `.minime-worktree.json` Marker**
    - An agent writes a fake `.minime-worktree.json` in an attempt to claim another project's worktree. Cleanup reconciles marker against durable DB records; mismatch causes deletion to be DENIED (`FAILURE` / `CONFLICT`).

18. **Scenario: Worktree Exists but Checked-Out SHA/Branch Mismatches Expected**
    - An existing worktree whose Git HEAD is on branch `feature-X` when job expects `architecture/stage-c` is detected; guard rejects execution with `FAILURE` / `CONFLICT`.

19. **Scenario: Agent Shell Command `cd /opt/minime/app && touch x`**
    - An agent sub-process attempts shell write into `RUNTIME`. OS process write confinement blocks the syscall with EPERM/EACCES, preventing live file modification.

20. **Scenario: Agent Absolute Path Write Outside Worktree**
    - An agent attempts to write to `/etc/config` or `/tmp/payload`. OS process write confinement intercepts the write syscall and denies execution.

21. **Scenario: Agent Mutates Symlink inside Worktree Pointing to `RUNTIME`**
    - An agent creates a symlink `worktree/link` -> `/opt/minime/app/main.py` and writes through the symlink. OS process write confinement resolves realpath and denies the write syscall.

---

## Out of Scope

The following architectural areas are explicitly OUT OF SCOPE for Stage C:

- **Stage D**: Durable intake and closure sagas.
- **Stage E**: Broad API CQS, read-model projection purity.
- **Stage F**: Database transaction boundary and concurrency convergence.
- **Stage G**: Scheduler capacity and queue redesign.
- **Stage H**: Broad agent and OpenSpec governance convergence.
- **Stage I**: Full adversarial program across all stages.
- **Stage J**: Production preflight and active deployment activation.
- Model selection policy and LLM provider routing.
- Dashboard UI redesign.
