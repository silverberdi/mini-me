# Durable Intake Workspace Isolation & Artifact Publication Specification

## ADDED Requirements

### Requirement: Durable Intake Workspace Ownership
The system MUST track intake workspace ownership via a dedicated `IntakeWorkspaceOwnership` domain and database entity bound to `project_id`, `item_key`, `saga_id`, `change_name`, `canonical_workspace_path`, `base_sha`, `creation_state`, and `publication_state`.

#### SCENARIO: Managed Repository Immutability During Intake
- **GIVEN** a BacklogItem undergoing autonomous intake preparation
- **WHEN** OpenSpec generation, readiness evaluation, issue binding, or artifact publication executes
- **THEN** the canonical managed repository root (`/opt/minime/repos/mini-me`) MUST remain a clean Git checkout with 0 untracked or modified files.

#### SCENARIO: Stage C Mutation Authorization for Intake Workspaces
- **GIVEN** a caller attempting to write OpenSpec artifacts
- **WHEN** `ManagedWorkspaceGuard.authorize_workspace_mutation` evaluates the write request
- **THEN** mutation MUST be authorized ONLY if a valid `IntakeWorkspaceOwnership` record exists with `creation_state == ACTIVE`, target path resides within `canonical_workspace_path`, and purpose is `OPENSPEC_AUTHORING` or `INTAKE_ARTIFACT_UPDATE`. Direct writes to `managed_repository_root` MUST be rejected with `ManagedWorkspaceGuardDeniedError`.

#### SCENARIO: Single Authoritative Readiness Source for Admission
- **GIVEN** a BacklogItem evaluated for Definition of Ready (DoR) scheduler admission
- **WHEN** `ReadinessService.evaluate_and_persist_change_readiness` executes
- **THEN** readiness MUST evaluate ONLY a verified published Git artifact identity (`published_ref` = `refs/minime/intake/<change_name>`, `published_sha`, `canonical_repository_identity`). An item MUST NOT become scheduler-admission `READY` based solely on an unpublished intake workspace.

#### SCENARIO: Compare-And-Swap Ref Publication Update Authority
- **GIVEN** an active intake workspace with committed OpenSpec artifacts
- **WHEN** `INTAKE_ARTIFACT_PUBLISH` external action executes
- **THEN** publication to remote `refs/minime/intake/<change_name>` MUST use compare-and-swap (CAS) semantics matching the expected previous published SHA. Blind force push MUST NOT be performed. CAS mismatch MUST fail closed to `NEEDS_HUMAN` with reason `conflicting_intake_publication_ref`.

#### SCENARIO: Main Advancement Pre-Admission Reconciliation
- **GIVEN** a published intake change at `published_sha = P` with `base_sha = A`
- **WHEN** canonical `origin/main` advances to commit `B` before admission (where `P` is not merged and `A != B`)
- **THEN** scheduler admission MUST reject execution from stale base `A` and materialize a new published candidate onto current main `B` without mutating commit `P`, CAS-updating `published_ref` to new `published_sha = P2`. If materialization conflicts, the item MUST transition to `NEEDS_HUMAN` (`main_advancement_conflict_detected`).

#### SCENARIO: Deterministic Execution Handoff Algorithm
- **GIVEN** an admitted execution run (`OrchestrationWorktreeOwnership`)
- **WHEN** execution worktree creation executes
- **THEN** the system MUST resolve current main `B`, verify published artifact `P`, create execution worktree from `B`, materialize ONLY the OpenSpec artifact tree from `P` onto `B`, verify hash provenance, and record `canonical_base_sha = B` and `published_sha = P` in durable handoff evidence.

#### SCENARIO: Git Commit Authority and Fingerprint Recovery
- **GIVEN** OpenSpec file authoring in an active intake workspace
- **WHEN** `INTAKE_GIT_COMMIT` external action executes
- **THEN** the system MUST verify `git status` is clean before authoring, commit ONLY manifest files (`proposal.md`, `tasks.md`, `design.md`, `specs/*.md`), enforce clean `git status` after commit, fail closed (`UnsafeIntakeWorkspaceStateError`) if unexpected files exist, and verify tree SHA-256 hash fingerprint during crash recovery.

#### SCENARIO: Cleanup Authority Semantics
- **GIVEN** an intake workspace eligible for cleanup after execution admission or terminal cancellation
- **WHEN** cleanup executes
- **THEN** deletion MUST be authorized ONLY when `creation_state` is `RELEASED_PENDING_CLEANUP` or `FAILED_PENDING_CLEANUP`, and deletion MUST require 4-way corroboration: (1) DB record, (2) canonical path equality, (3) Git worktree observation, and (4) root marker file `.minime_intake_workspace`.

#### SCENARIO: Legacy Dirty-State Read-Only Reconciliation and Adoption
- **GIVEN** untracked OpenSpec directories under `managed_repository_root/openspec/changes/` lacking historical `IntakeWorkspaceOwnership` records
- **WHEN** post-deployment reconciliation executes
- **THEN** the system MUST perform read-only attribution against active sagas, issue actions, project bindings, and template hashes. Provable artifacts MUST be copied into a NEW owned intake workspace and published to `refs/minime/intake/<cname>` without dirtying base, while unprovable/ambiguous directories MUST transition to `NEEDS_HUMAN` (`legacy_unowned_intake_artifacts_detected`).
