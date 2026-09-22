# Design: Managed Repository Runtime Isolation

## Context and Architectural Laws

Stage C (`managed-repository-runtime-isolation`) is governed by the foundational architectural laws of mini me:

1. **One transition has one writer** (Stage A: `LifecycleTransitionAuthority`).
2. **Missing evidence never becomes success** (Stage B: `ExternalActionResult` fail-closed semantics).
3. **Projection/observation cannot resurrect terminal state**.
4. **External effects must be verifiable, idempotent, resumable**.
5. **Deployed runtime must never be the managed project workspace**.

Stage C focuses EXCLUSIVELY on Law 5 and its direct filesystem, repository, and operational implications.

---

## Workspace Model Architecture

The system categorizes all filesystem paths into four explicit workspace roles:

```
+-----------------------------------------------------------------------------------+
|                                  MINI ME HOST                                     |
|                                                                                   |
|  +-----------------------------------------------------------------------------+  |
|  | [RUNTIME] Runtime Checkout (e.g. /opt/minime/app)                           |  |
|  | - Running service binary & process code                                     |  |
|  | - STRICTLY READ-ONLY for SDLC operations                                    |  |
|  | - NEVER a managed workspace or worktree target                              |  |
|  +-----------------------------------------------------------------------------+  |
|                                                                                   |
|  +-----------------------------------------------------------------------------+  |
|  | TRUSTED MANAGED ROOT (e.g. /opt/minime/managed-projects)                    |  |
|  |                                                                             |  |
|  |  +-----------------------------------------------------------------------+  |  |
|  |  | MANAGED REPOSITORY ROOT (e.g. .../<project-id>/repository)             |  |  |
|  |  | - Canonical base checkout & Git history for project                     |  |  |
|  |  | - Contains Project OpenSpec Workspace (openspec/specs/, changes/)       |  |  |
|  |  | - Mutations restricted to authorized canonical sync/fetch operations    |  |  |
|  |  +-----------------------------------------------------------------------+  |  |
|  |                                                                             |  |
|  |  +-----------------------------------------------------------------------+  |  |
|  |  | EXECUTION WORKTREES (e.g. .../<project-id>/worktrees/<run-id>)        |  |  |
|  |  | - Ephemeral isolated workspaces for jobs/runs/candidates               |  |  |
|  |  | - Carries explicit ownership metadata (project_id, run_id, branch)     |  |  |
|  |  | - Agent code edits & review testing executed here ONLY                |  |  |
|  |  +-----------------------------------------------------------------------+  |  |
|  +-----------------------------------------------------------------------------+  |
+-----------------------------------------------------------------------------------+
```

### 1. Runtime Checkout (`RUNTIME`)
- The active, running deployment checkout of mini me (e.g. `/opt/minime/app` or local service checkout).
- Treated as a **read-only deployment artifact** from the perspective of project SDLC management.
- Forbidden as an implementation target, worktree root, OpenSpec sync/archive destination, branch modification target, or agent writing workspace.

### 2. Managed Repository Root (`MANAGED_REPOSITORY`)
- The canonical base checkout and Git history repository for a registered project, residing under a configured trusted managed root (e.g. `/opt/minime/managed-projects/<project-id>/repository`).
- Physically and logically distinct from `RUNTIME`.
- Hosts canonical project Git refs and default base branch (`main`/`master`).

### 3. Execution Worktree (`EXECUTION_WORKTREE`)
- An ephemeral Git worktree or isolated workspace derived from `MANAGED_REPOSITORY` for a specific job, run, or change.
- Resides strictly under `<managed-root>/<project-id>/worktrees/<worktree-id>`.
- Bound to explicit job ownership metadata (`project_id`, `job_id`, `run_id`, `change_name`, `branch`, `source_base_sha`).
- Agent code edits, pytest executions, auditor reviews, and candidate commits MUST happen strictly inside an `EXECUTION_WORKTREE`.

### 4. Project OpenSpec Workspace (`PROJECT_OPENSPEC_WORKSPACE`)
- The OpenSpec artifacts (`openspec/specs/`, `openspec/changes/`) belonging to the managed project.
- All OpenSpec operations (`new`, `apply`, `verify`, `sync`, `archive`) for a managed project MUST resolve against the project's `MANAGED_REPOSITORY` or `EXECUTION_WORKTREE`, NEVER against the `RUNTIME` checkout.

---

## Self-Hosting Isolation Principles

When mini me manages its own repository (`mini-me` managing `mini-me`):

1. `RUNTIME` (e.g. `/opt/minime/app`) and `MANAGED_REPOSITORY` (e.g. `/opt/minime/managed-projects/mini-me/repository`) **MUST remain two distinct filesystem and repository identities**.
2. **Identity Equality Fallacy**: Equality of repository URL (`github.com/silverberdi/mini-me`), project name (`mini-me`), commit SHA (`1f0d15...`), or working tree contents DOES NOT authorize using `RUNTIME` as a managed workspace.
3. Agents working on `mini-me` tasks write code inside `/opt/minime/managed-projects/mini-me/worktrees/<run-id>`, NEVER in `/opt/minime/app`.
4. OpenSpec sync and archive for `mini-me` changes update `/opt/minime/managed-projects/mini-me/repository`, NEVER `/opt/minime/app`.
5. Updating `/opt/minime/app` occurs ONLY via an explicit, separate deployment boundary step.

---

## Project Managed Repository Binding

Every managed project MUST have a persisted, verifiable binding:

```python
class WorkspaceRole(str, Enum):
    RUNTIME = "RUNTIME"
    MANAGED_REPOSITORY = "MANAGED_REPOSITORY"
    EXECUTION_WORKTREE = "EXECUTION_WORKTREE"
    UNKNOWN = "UNKNOWN"

class ProjectManagedRepositoryBinding(BaseModel):
    project_id: str
    repository_url: str
    canonical_git_remote: str  # e.g. "origin", "git@github.com:org/repo.git"
    managed_repository_root: Path  # Absolute, canonicalized path
    worktree_parent_dir: Path      # Absolute, canonicalized path under managed root
    default_base_branch: str       # e.g. "main"
    ownership_marker_filename: str = ".minime-managed-project.json"
    created_at: datetime
    updated_at: datetime
```

### Binding Constraints
- Path guessing, `cwd` inference, directory name heuristics, and title matching are **STRICTLY FORBIDDEN**.
- If a project binding is missing or unverified, fresh execution admission is **BLOCKED**.
- The `managed_repository_root` MUST NOT equal, contain, or be contained by `RUNTIME`.

---

## Central `ManagedWorkspaceGuard` Architecture

All filesystem and Git side effects across mini me MUST pass through a central authority: `ManagedWorkspaceGuard`.

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
6. **Git Remote Verification**: Execute `git remote get-url origin` on target repository to verify canonical remote matches `binding.repository_url`.
7. **Operation Authorization**: Verify requested operation is permitted for the classified workspace role:
   - `RUNTIME`: ALL mutations DENIED (`POLICY_DENIED`).
   - `MANAGED_REPOSITORY`: Base branch fetch, canonical OpenSpec sync/archive, and worktree spawn ALLOWED. Code edits and candidate commits DENIED.
   - `EXECUTION_WORKTREE`: Agent code edits, test execution, candidate branch/commit ALLOWED.
8. **Return Typed Decision**: Return `WorkspaceMutationDecision` with fail-closed Stage B outcome semantics.

---

## Inventory of Covered Writers

The following operations MUST pass through `ManagedWorkspaceGuard` before execution:

1. **`WorktreeManager`**: Creation, setup, and deletion of Git worktrees.
2. **Orchestration Startup & Setup**: Worktree initialization and base checkout.
3. **Primary Implementer Execution**: Agent workspace resolution and file modification tools.
4. **Reviewer Execution**: Auditor checkout, test runner, and patch application.
5. **Remediation & Integration Worktrees**: Worktrees created for conflict resolution or candidate remediation.
6. **`OpenSpecSyncService`**: Reading delta specs and writing canonical main specs in `openspec/specs/`.
7. **`OpenSpecArchiveService`**: Relocating completed change directories to `openspec/changes/archive/`.
8. **OpenSpec Change Authoring**: `openspec new` and change proposal updates.
9. **Git Branch Operations**: Creation, checkout, and deletion of local/remote branches.
10. **Git Commit & Push**: Authoring candidate commits and pushing to remotes.
11. **Post-Merge Cleanup**: Local branch deletion, worktree pruning, and archive verification.
12. **Restart Recovery**: Re-attaching to or cleaning up worktrees after process restart.
13. **Control Plane / Manual Reconciliation**: Manual operator actions touching workspace files.
14. **Self-Hosting Workflows**: All SDLC operations when managing `mini-me`.
15. **Deployment Handoff Boundary**: Promotion artifact packaging.

---

## Runtime Immutability Rules

The deployed `RUNTIME` checkout is strictly immutable for SDLC activities:

### Forbidden on `RUNTIME`
- Agent file creation, modification, or deletion.
- `git checkout`, `git branch`, `git commit`, `git push`, or `git reset`.
- `openspec new`, `openspec sync`, `openspec archive`, or `openspec validate` targeted at runtime paths.
- `git worktree add` deriving from runtime or pointing into runtime.
- Branch cleanup commands inspecting or altering runtime refs.
- Direct process self-modification or hot-patching.

### Permitted on `RUNTIME`
- Explicit, separate deployment pipeline execution (service update).
- Read-only inspection of runtime SHA, version, or status.
- Reading configuration or host environment secrets.

---

## Deployment Boundary

Stage C defines the boundary separating candidate development from runtime deployment:

```
+------------------------------------+           +------------------------------------+
|         MANAGED REPOSITORY         |           |          DEPLOYED RUNTIME          |
|                                    |           |                                    |
| Verified Candidate SHA:            |  Deploy   | Active Runtime SHA:                |
| 4b353cfcc31451264fd32c...          | --------> | 4b353cfcc31451264fd32c...          |
| Location:                          |  Process  | Location:                          |
| /opt/minime/managed/.../repository |           | /opt/minime/app                    |
+------------------------------------+           +------------------------------------+
```

### Deployment Boundary Invariants
- Deployment MAY fetch, copy, containerize, or promote an exact, verified candidate commit SHA to the runtime destination and restart the process.
- Deployment MUST NOT grant managed repository or execution worktree semantics to `RUNTIME`.
- Deployment MUST NOT use `RUNTIME` as the source worktree for the next change.
- Equality of runtime SHA and managed candidate SHA does NOT collapse filesystem identity.

---

## Git Identity & Remote Verification

Before permitting mutations in a managed repository or worktree:

1. **Repository Root Proof**: `git rev-parse --show-toplevel` MUST match the expected canonical path.
2. **Git Remote Proof**: `git remote get-url origin` MUST match `binding.canonical_git_remote`.
3. **Ownership Marker**: The repository directory MUST contain a valid `.minime-managed-project.json` file carrying the correct `project_id`.
4. **Project Mismatch Denial**: A valid Git repository belonging to a different project URL or ID MUST be rejected with `FAILURE` / `CONFLICT`.

---

## Worktree Ownership & Cleanup Safety

To prevent destructive globbing or accidental deletion of unowned directories:

1. **Explicit Metadata File**: Every execution worktree directory MUST contain a `.minime-worktree.json` metadata file:
   ```json
   {
     "project_id": "mini-me",
     "job_id": "job-123",
     "run_id": "run-456",
     "change_name": "managed-repository-runtime-isolation",
     "source_repository": "git@github.com:silverberdi/mini-me.git",
     "source_base_sha": "1f0d15cc31cc1fbc6f086b76b02c17706b742e51",
     "branch": "architecture/managed-repository-runtime-isolation",
     "created_at": "2026-09-21T21:24:00Z"
   }
   ```
2. **Worktree Cleanup Rule**: `WorktreeManager` and post-merge cleanup tasks MUST ONLY delete worktrees whose `.minime-worktree.json` can be read, parsed, and authoritatively matched to `project_id` and `job_id`.
3. **Ambiguous Folder Deletion**: Unowned, un-marked, or ambiguous folders encountered during cleanup MUST NOT be deleted automatically; they MUST be reported as `UNKNOWN` / `EVIDENCE_INSUFFICIENT` and flagged for operator review.

---

## Legacy Workspace Aliasing Reconciliation

For existing mini me installations where `RUNTIME` historically aliased the project checkout:

1. **Aliasing Detection**: Startup readiness checks inspect project bindings. If `managed_repository_root` overlaps with `RUNTIME` (or if no binding exists and `cwd` is `RUNTIME`), legacy aliasing is flagged.
2. **Admission Blocking**: Fresh work admission is strictly `BLOCKED` until reconciliation completes.
3. **Reconciliation Process**:
   - Create a dedicated managed repository root outside `RUNTIME` (e.g. `/opt/minime/managed-projects/<project-id>/repository`).
   - Clone or initialize the canonical Git repository into the managed root.
   - Verify Git remote, HEAD SHA, and ownership marker.
   - Persist updated `ProjectManagedRepositoryBinding`.
4. Only after successful reconciliation is admission unblocked.

---

## Observability & Telemetry

The system MUST expose the following workspace isolation telemetry:

- `project_id` and active `managed_repository_root` path.
- Current `managed_repository` HEAD SHA and verified `canonical_git_remote`.
- Deployed `RUNTIME` path and active `RUNTIME` SHA.
- Isolation status boolean: `is_runtime_isolated` (True ONLY if `RUNTIME` and `MANAGED_REPOSITORY` paths do not overlap).
- List of active `EXECUTION_WORKTREES` with verified ownership metadata.
- Metric counter: `workspace_mutation_denied_total` (labels: `project_id`, `reason_code`, `attempted_operation`).

---

## Failure Semantics (Stage B Integration)

Workspace identity and mutation guard decisions MUST map directly to Stage B typed outcome semantics:

| Failure Case | Outcome | Reason Code | Retry Safety | Action |
| :--- | :--- | :--- | :--- | :--- |
| Workspace identity unproven or missing | `UNKNOWN` | `EVIDENCE_INSUFFICIENT` | `UNSAFE` | Block execution; request binding |
| Mutation requested against `RUNTIME` | `FAILURE` | `POLICY_DENIED` | `UNSAFE` | Block mutation; log security violation |
| Symlink escape / path traversal | `FAILURE` | `POLICY_DENIED` | `UNSAFE` | Block mutation; reject path |
| Git remote mismatch | `FAILURE` | `CONFLICT` | `UNSAFE` | Block mutation; reject repository |
| Unowned/ambiguous worktree cleanup | `UNKNOWN` | `EVIDENCE_INSUFFICIENT` | `UNSAFE` | Preserve folder; require human review |
| Filesystem I/O or stat error | `UNKNOWN` | `UNOBSERVABLE` | `SAFE` | Retry query; block mutation |

---

## Admission Fence Rules

Fresh work MUST NOT advance from `READY` to `IN_PROGRESS` if any of the following fence conditions hold:

1. `ProjectManagedRepositoryBinding` is missing or unpersisted for the target project.
2. `managed_repository_root` equals, contains, or is contained by `RUNTIME`.
3. `ManagedWorkspaceGuard` fails Git remote verification against `canonical_git_remote`.
4. Workspace role classification yields `RUNTIME` or `UNKNOWN`.
5. Creation of an `EXECUTION_WORKTREE` under the authorized managed root fails postcondition verification.

---

## Required Invariants

- **Invariant 1**: `RUNTIME` path and `MANAGED_REPOSITORY` path MAY NEVER resolve to the same filesystem identity.
- **Invariant 2**: A mutating SDLC action against `RUNTIME` MUST ALWAYS be denied (`POLICY_DENIED`).
- **Invariant 3**: A workspace target outside the trusted managed root MUST ALWAYS be denied (`POLICY_DENIED`).
- **Invariant 4**: A managed path bound to a different `project_id` MUST ALWAYS be denied (`CONFLICT`).
- **Invariant 5**: A Git repository remote mismatch MUST ALWAYS block execution (`CONFLICT`).
- **Invariant 6**: Unknown workspace identity MUST ALWAYS block mutation (`EVIDENCE_INSUFFICIENT`).
- **Invariant 7**: OpenSpec sync and archive operations CANNOT run against `RUNTIME` paths.
- **Invariant 8**: Self-hosting `mini-me` MUST use a separate managed repository directory distinct from `RUNTIME`.
- **Invariant 9**: Worktree cleanup CANNOT delete an unowned, un-marked, or ambiguous directory.
- **Invariant 10**: Deployment MAY update `RUNTIME` from a verified artifact or commit SHA without granting managed-workspace semantics to `RUNTIME`.

---

## Adversarial Scenarios

The test plan MUST validate the following 18 adversarial scenarios:

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
   - A managed repository directory whose `git remote get-url origin` returns `git@github.com:attacker/fake-repo.git` instead of `binding.canonical_git_remote` is rejected with `FAILURE` / `CONFLICT`.

7. **Scenario: Repo Copied from Correct Project but `.git` Points Elsewhere**
   - A repository folder with correct code files whose `.git` file or gitdir points to a external repository is rejected during remote verification with `FAILURE` / `CONFLICT`.

8. **Scenario: Stale Workspace Binding**
   - A project binding pointing to a deleted or unmounted filesystem path returns `UNKNOWN` / `EVIDENCE_INSUFFICIENT` and blocks admission.

9. **Scenario: Missing Managed Repository Directory**
   - When `managed_repository_root` does not exist on disk, fresh work admission is blocked with `UNKNOWN` / `EVIDENCE_INSUFFICIENT`.

10. **Scenario: Corrupt `.git` Directory in Managed Repo**
    - When `git rev-parse --show-toplevel` fails due to a corrupted `.git` folder, mutation is blocked with `UNKNOWN` / `UNOBSERVABLE`.

11. **Scenario: Inaccessible Filesystem / Permission Error**
    - When filesystem `stat` or `os.listdir` encounters `EPERM` / `EACCES`, the guard returns `UNKNOWN` / `UNOBSERVABLE` without assuming default success.

12. **Scenario: Existing Unmanaged Worktree with Matching Job-like Name**
    - A directory `worktrees/job-123` lacking a valid `.minime-worktree.json` metadata file is encountered during cleanup; cleanup skips deletion and returns `UNKNOWN` / `EVIDENCE_INSUFFICIENT`.

13. **Scenario: Same Repo URL Registered to Multiple Project IDs**
    - Registering `git@github.com:org/repo.git` under `project-A` and `project-B` enforces distinct managed repository roots (`managed-projects/project-A/repository` vs `managed-projects/project-B/repository`). Cross-project mutation is rejected with `FAILURE` / `CONFLICT`.

14. **Scenario: Self-Hosting `mini-me` Execution Isolation**
    - Executing a `mini-me` self-hosting task creates worktree in `/opt/minime/managed-projects/mini-me/worktrees/run-789`. File edits by implementer alter `run-789`, while `/opt/minime/app` remains 100% unchanged.

15. **Scenario: Process Restart after Partial Worktree Creation**
    - Process crashes midway through `git worktree add`. Restart recovery inspects worktree directory: lacking completed `.minime-worktree.json`, recovery prunes partial worktree safely and re-initializes.

16. **Scenario: Worktree Exists but Checked-Out SHA/Branch Mismatches Expected**
    - An existing worktree whose Git HEAD is on branch `feature-X` when job expects `architecture/stage-c` is detected; guard rejects execution with `FAILURE` / `CONFLICT`.

17. **Scenario: Runtime Deployed SHA Equals Managed Candidate SHA**
    - `RUNTIME` SHA is `1f0d15...` and `MANAGED_REPOSITORY` SHA is `1f0d15...`. Guard verifies path distinction (`/opt/minime/app` vs `/opt/minime/managed-projects/...`). Mutation against `/opt/minime/app` is STILL DENIED (`POLICY_DENIED`). SHA equality does NOT grant managed-workspace status to runtime.

18. **Scenario: OpenSpec Sync Targeted at `RUNTIME` Path**
    - Calling `OpenSpecSyncService` with target path `/opt/minime/app/openspec/specs` is intercepted by `ManagedWorkspaceGuard` and rejected with `FAILURE` / `POLICY_DENIED`.

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
