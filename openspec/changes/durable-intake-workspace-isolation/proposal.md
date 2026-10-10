# Proposal: Durable Intake Workspace Isolation & Artifact Publication

## Intent
Autonomous intake currently authors OpenSpec artifacts directly under the managed repository root (`/opt/minime/repos/mini-me/openspec/changes/<change-name>`) during backlog preparation. This dirties the canonical managed repository before any execution Run or Job exists, violating managed repository immutability and triggering production hard stops.

This proposal introduces a first-class, durable intake workspace domain model (`IntakeWorkspaceOwnership`), an isolated Stage C worktree topology, saga-driven phase progression, authoritative artifact publication (`refs/minime/intake/<change_name>`), refactored single-authority readiness/discovery contracts, and deterministic execution handoff, guaranteeing that the managed repository base remains 100% clean at all times.

## Proposed Changes

### 1. Domain Ownership Model: `IntakeWorkspaceOwnership`
- Add `IntakeWorkspaceOwnership` SQLAlchemy model, Pydantic domain model, and PostgreSQL repository.
- Binds durable intake workspace identity to `project_id`, `item_key`, `saga_id`, `change_name`, `canonical_workspace_path`, `base_sha`, `creation_state`, and `publication_state`.
- Strict PostgreSQL unique constraints prevent path collisions, double-writer ownership, or multi-workspace ambiguity.

### 2. Workspace Topology & Stage C Mutation Guard
- Physical location: `<worktree_parent_dir>/intake-workspaces/<project_id>/<workspace_id>`.
- Fully isolated from `/opt/minime/repos/mini-me` (managed repository root) and `/opt/minime/app` (runtime).
- `ManagedWorkspaceGuard` extended to authorize `OPENSPEC_AUTHORING` only within active `IntakeWorkspaceOwnership` paths (`creation_state == ACTIVE`), rejecting any direct writes to `managed_repository_root`.

### 3. Single Authoritative Readiness Source
- **Pre-Publication Validation:** May inspect the active intake workspace during authoring for early generator feedback. Cannot make an item scheduler-admission `READY`.
- **Authoritative Readiness for Admission:** Admission readiness (`ReadinessService.evaluate_and_persist_change_readiness()`) MUST ONLY inspect a verified published Git artifact identity (`published_ref` = `refs/minime/intake/<change_name>`, `published_sha`, `canonical_repository_identity`). An item MUST NOT become scheduler-admission `READY` based solely on an unpublished workspace.

### 4. Authoritative Ref Publication (Compare-And-Swap)
- OpenSpec artifacts generated in the intake workspace are committed and published to remote Git ref `refs/minime/intake/<change_name>` using compare-and-swap (CAS) update semantics.
- Force push is forbidden; CAS mismatch or ambiguous push uses observe-before-repeat or transitions to `NEEDS_HUMAN`.

### 5. Deterministic Main Advancement & Execution Handoff
- If canonical `main` advances from `A` to `B` before admission, a new intake publication candidate is deterministically materialized onto `B` and CAS-updated to `P2`.
- When an execution run is admitted, `OrchestrationWorktreeOwnership` creates an execution worktree from base `B` and deterministically materializes the published OpenSpec artifact tree from `published_sha` `P`.

### 6. Legacy Dirty-State Read-Only Reconciliation & Adoption
- Historical untracked directories lacking `IntakeWorkspaceOwnership` are evaluated by read-only attribution (`PROVABLE_LEGACY_ARTIFACT` vs `AMBIGUOUS_LEGACY_ARTIFACT`).
- Provable legacy artifacts are copied into a NEW owned intake workspace and published without dirtying managed base; unprovable directories transition to `NEEDS_HUMAN`.

## Verification Plan
- Unit & integration tests for workspace creation, Stage C isolation, saga phase transitions, CAS publication, single-authority readiness, discovery, main advancement reconciliation, execution handoff, 4-way cleanup, and legacy adoption.
- OpenSpec validation and strict code checks.
