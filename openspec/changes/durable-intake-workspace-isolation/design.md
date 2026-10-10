# Design: Durable Intake Workspace Isolation & Artifact Publication

## Architecture & Design Decisions

### 1. Domain Model: `IntakeWorkspaceOwnership`
In `src/minime/domain/models.py` and `src/minime/db/models.py`:
Define `IntakeWorkspaceOwnership` to represent durable ownership of an isolated intake authoring workspace:
- `workspace_id`: String / UUID primary key
- `project_id`: String foreign key
- `item_key`: String (BacklogItem key)
- `saga_id`: String (DurableSaga ID of type `INTAKE`)
- `change_name`: String (slugified OpenSpec change name)
- `canonical_workspace_path`: String (canonicalized filesystem path)
- `canonical_repository_identity`: String (e.g. `github.com/silverberdi/mini-me`)
- `base_sha`: String (Git commit SHA of canonical main at worktree creation)
- `head_sha`: String (Git commit SHA of current intake workspace HEAD)
- `creation_state`: `IntakeWorkspaceCreationState` (`RESERVED`, `CREATING`, `ACTIVE`, `RELEASED_PENDING_CLEANUP`, `RELEASED_CLEANED`, `FAILED_PENDING_CLEANUP`, `FAILED_CLEANED`, `NEEDS_HUMAN`)
- `publication_state`: `IntakeWorkspacePublicationState` (`UNPUBLISHED`, `PUBLISHING`, `PUBLISHED`, `PUBLICATION_FAILED`)
- `published_ref`: String | None (`refs/minime/intake/<change_name>`)
- `published_sha`: String | None (Git commit SHA of published ref)
- `created_at`, `updated_at`, `released_at`: UTC timestamps

#### DB Constraints (`alembic` migration & PostgreSQL):
- `uq_intake_workspace_active_item`: UNIQUE `(project_id, item_key)` WHERE `creation_state IN ('RESERVED', 'CREATING', 'ACTIVE')`
- `uq_intake_workspace_active_path`: UNIQUE `(canonical_workspace_path)` WHERE `creation_state IN ('RESERVED', 'CREATING', 'ACTIVE')`
- `uq_intake_workspace_active_saga`: UNIQUE `(saga_id)` WHERE `creation_state IN ('RESERVED', 'CREATING', 'ACTIVE')`

### 2. Workspace Physical Topology & Stage C Mutation Authority
- Physical Topology: `<worktree_parent_dir>/intake-workspaces/<project_id>/<workspace_id>`.
- Isolated from `/opt/minime/repos/mini-me` (managed repository root) and `/opt/minime/app` (runtime).
- `ManagedWorkspaceGuard.authorize_workspace_mutation()` extended:
  - Purpose `OPENSPEC_AUTHORING` or `INTAKE_ARTIFACT_UPDATE` requires `creation_state == ACTIVE` on `IntakeWorkspaceOwnership`.
  - Target path MUST reside within `IntakeWorkspaceOwnership.canonical_workspace_path`.
  - Writing directly to `managed_repository_root` is strictly rejected with `ManagedWorkspaceGuardDeniedError`.

### 3. Single Authoritative Readiness Source
- **Pre-Publication Validation:** `ReadinessService.validate_intake_workspace_preflight()` inspects files inside active workspace (`canonical_workspace_path`) during authoring (`WORKSPACE_ACTIVE` phase) for early feedback.
- **Authoritative Readiness for Admission:** Admission readiness (`ReadinessService.evaluate_and_persist_change_readiness()`) MUST ONLY inspect a verified published Git artifact identity (`artifact_source_type="PUBLISHED_REF"`):
  - `canonical_repository_identity`
  - `published_ref` (`refs/minime/intake/<change_name>`)
  - `published_sha`
  - `change_name`
  - Valid artifact tree rooted at `published_sha` containing proposal, tasks, design, and specs.
- An item MUST NOT become scheduler-admission `READY` based solely on an unpublished workspace.

### 4. Publication Ref Update Authority (Compare-And-Swap)
- **Ref Namespace:** Remote ref `refs/minime/intake/<change_name>` on canonical repository (`origin`). Remote publication guarantees durability across host failures.
- **CAS Contract:**
  - Initial publication: Permitted ONLY if `refs/minime/intake/<change_name>` is absent on remote (`expected_old_sha = None`).
  - Update/re-authoring: MUST supply exact `expected_old_sha` matching current remote ref SHA.
  - Blind force-push (`git push --force`) is STRICTLY FORBIDDEN.
  - CAS mismatch or concurrent update returns `ExternalOutcome.FAILURE` with reason `REF_CAS_MISMATCH` -> transitions saga to `NEEDS_HUMAN` (`conflicting_intake_publication_ref`).
  - Ambiguous push -> reserve action as `AMBIGUOUS`, observe remote ref SHA. If remote ref SHA matches candidate commit SHA, mark `COMPLETED`.
  - `published_sha` on `IntakeWorkspaceOwnership` is updated ONLY AFTER authoritative remote ref observation.

### 5. Base SHA / Main Advancement Reconciliation Contract
When canonical `main` advances from `A` to `B` before admission while intake is at `base_sha = A` and `published_sha = P`:
- System checks if `published_sha` is an ancestor of or equal to `origin/main` (`B`).
- If `origin/main` has advanced to `B`, and `P` is not merged into `B` and `A != B`:
  1. Do NOT mutate existing published commit `P`.
  2. Construct a NEW intake publication candidate based on `B`.
  3. Deterministically materialize the authoritative OpenSpec artifact manifest from `P` onto `B`.
  4. Validate conflict-free application.
  5. Commit new candidate `P2`.
  6. CAS-update `refs/minime/intake/<change_name>` from `P` -> `P2`.
  7. Persist new `base_sha = B` and `published_sha = P2` on `IntakeWorkspaceOwnership` ONLY after remote observation.
  8. If deterministic materialization conflicts: transition saga to `NEEDS_HUMAN` (`main_advancement_conflict_detected`).
- No blind `git rebase` or force push.

### 6. Workspace Mutation vs External Action Classification
- **Local Guarded Mutations:** Local directory allocation under `<worktree_parent_dir>/intake-workspaces/`, local OpenSpec file formatting, local Git status checks.
- **Durable DB Mutations:** DB reservation (`creation_state = RESERVED`), state transitions (`ACTIVE`, `RELEASED_PENDING_CLEANUP`), DB update of `published_ref` & `published_sha`.
- **External Actions & Side Effects (Reserved in `orchestration_external_actions`):**
  - `INTAKE_WORKTREE_CREATE`: Git worktree creation command (`git worktree add`).
  - `INTAKE_GIT_COMMIT`: Git commit creation in intake worktree (`git commit`).
  - `ISSUE_CREATE`: Remote GitHub Issue creation API call.
  - `PROJECT_ITEM_ADD`: Remote GitHub Project v2 add API call.
  - `INTAKE_ARTIFACT_PUBLISH`: Remote Git ref push/update (`git push origin <head_sha>:refs/minime/intake/<cname>`).

### 7. Git Commit Authority & Crash Recovery Fingerprint
- **Worktree Branch:** `intake/<change_name>` in `<canonical_workspace_path>`.
- **Commit Author:** `mini-me-bot <bot@minime.internal>`.
- **Commit Message:** `docs(openspec): author canonical artifacts for <change_name>`
- **Clean-Before-Authoring:** `git status --porcelain` MUST be 100% clean prior to file writes.
- **Allowed Changed Paths:** ONLY files under `<canonical_workspace_path>/proposal.md`, `tasks.md`, `design.md`, `specs/*.md`.
- **Unexpected Files:** Any file outside manifest causes immediate fail-closed abort (`UnsafeIntakeWorkspaceStateError`).
- **Clean-After-Commit:** `git status --porcelain` MUST be 100% clean immediately following commit.
- **Crash Recovery Fingerprint:** `INTAKE_GIT_COMMIT` action key `commit:intake:<workspace_id>`. Crash recovery inspects `git log -1` and verifies commit tree matches expected fingerprint (`workspace_id`, `saga_id`, `change_name`, `base_sha`, exact SHA-256 file hashes). Adopts commit ONLY if tree and fingerprint match.

### 8. Extended INTAKE Saga Phase Machine
1. `INTAKE_CREATED`
2. `CONTEXT_CHECKED`
3. `WORKSPACE_RESERVED`
4. `WORKSPACE_ACTIVE`
5. `OPENSPEC_AUTHORED`
6. `ISSUE_BOUND`
7. `PROJECT_ITEM_BOUND`
8. `ARTIFACTS_PUBLISHED`
9. `READINESS_EVALUATED`
10. `READY`

### 9. Cleanup Ownership Semantics
- **Mutation Authority:** Held ONLY when `creation_state == ACTIVE`.
- **Cleanup Authority:** Held ONLY when `creation_state == RELEASED_PENDING_CLEANUP` or `FAILED_PENDING_CLEANUP`.
- **Terminal Historical Record:** `RELEASED_CLEANED` / `FAILED_CLEANED` (immutable, cannot authorize mutation or further cleanup).
- `NEEDS_HUMAN` state MUST NOT silently free a path if physical ownership remains unresolved.

### 10. Legacy Dirty-State Read-Only Reconciliation & Adoption
For historical untracked directories (`provider-capacity-drain-policy`, `pwa-card-spacing-vertical-rhythm`, `work-intake-modal-ux-redesign`):
- Read-only attribution checks active sagas, issue actions, project bindings, file manifests, and template hashes.
- **Outcome A (`PROVABLE_LEGACY_ARTIFACT`):** If all evidence matches, system creates a NEW isolated intake workspace (`IntakeWorkspaceOwnership`), copies ONLY the proven files into it, commits, publishes `refs/minime/intake/<cname>`, and updates `publication_state = PUBLISHED` without claiming historical false ownership.
- **Outcome B (`AMBIGUOUS_LEGACY_ARTIFACT`):** If unprovable or contradictory, item transitions to `NEEDS_HUMAN` (`legacy_unowned_intake_artifacts_detected`). No cleanup executed without human authority.

### 11. Discovery Authority (`PublishedIntakeArtifactSource`)
- `DiscoveryService` queries `PublishedIntakeArtifactSource` returning `project_id`, `change_name`, `published_ref`, `published_sha`, `canonical_repository_identity`.
- Verifies Git object existence via `git cat-file -t <published_sha>`. Zero base filesystem writes.

### 12. Execution Handoff Algorithm
When `SchedulerService.admit_work_item()` admits a `READY` item:
1. Resolve current canonical `main` SHA `B`.
2. Verify published artifact `P` (`published_sha`) and provenance from `published_ref`.
3. Create execution worktree (`OrchestrationWorktreeOwnership`) from `B`.
4. Materialize ONLY the authoritative OpenSpec artifact tree (`proposal.md`, `tasks.md`, `design.md`, `specs/*.md`) from `P` onto the execution worktree at `B`.
5. Verify resulting paths and hash provenance.
6. Record `canonical_base_sha = B` and `published_sha = P` in durable execution handoff evidence.
7. Fail closed immediately on conflict or unexpected path.
