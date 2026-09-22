# Proposal: Managed Repository Runtime Isolation

## Why

Currently in mini me, the orchestrator and execution services (including `WorktreeManager`, `OpenSpecSyncService`, `OpenSpecArchiveService`, `OrchestrationService`, and provider runners) frequently inspect or mutate the local working tree directory (`cwd`) directly. When mini me is executing in single-installation or self-hosting mode (where mini me manages its own repository, `mini-me`), there is a high risk of collapsing the **deployed runtime checkout** (the deployed code running mini me, e.g. `/opt/minime/app` or local repository root) with the **managed project working tree** (where code edits, OpenSpec changes, branch operations, and candidate commits are performed).

This structural aliasing violates a fundamental architectural law: **The deployed runtime must never be a managed project workspace**.

When the deployed runtime and managed workspace are aliased or unisolated:
1. Agent implementations or OpenSpec sync/archive operations can mutate the live running process files directly.
2. Ephemeral execution worktrees may be created inside or derived from the deployed runtime checkout.
3. Branch deletion or cleanup tasks may mutate or corrupt the deployed runtime's Git HEAD and working state.
4. Self-hosting mini me can perform self-modifying side effects, destroying auditability and reproducibility.
5. Path-guessing ("if `cwd` looks like the repo, use it") allows unverified, untrusted, or mismatched directories to be mutated.

Under Stage C (`managed-repository-runtime-isolation`), mini me enforces strict, canonical filesystem and repository isolation between:
- Deployed runtime checkout (`RUNTIME`)
- Managed repository root (`MANAGED_REPOSITORY`)
- Ephemeral execution worktrees (`EXECUTION_WORKTREE`)

Project OpenSpec workspaces (`openspec/specs/`, `openspec/changes/`) operate strictly as authorized logical subtrees located inside a `MANAGED_REPOSITORY` or `EXECUTION_WORKTREE`, and are never permitted inside `RUNTIME`.

## What Changes

- **Strict Workspace Model**: Explicitly separate workspace roles into exactly four enums: `RUNTIME`, `MANAGED_REPOSITORY`, `EXECUTION_WORKTREE`, and `UNKNOWN`. Treat Project OpenSpec Workspace as a logical capability subtree within `MANAGED_REPOSITORY` or `EXECUTION_WORKTREE`.
- **Self-Hosting Isolation Guarantee**: Require that when mini me manages its own repository (`mini-me`), the deployed runtime checkout (`/opt/minime/app` or equivalent) and the managed project repository (`<managed-root>/mini-me/repository`) remain strictly separate physical and logical identities. SHA equality does NOT collapse workspace identity.
- **Project Managed Repository Binding**: Define `ProjectManagedRepositoryBinding` carrying `project_id`, `canonical_repository_identity`, `remote_name`, `managed_repository_root`, `default_base_branch`, and ownership metadata. Require verified binding lookup; forbid path guessing, `cwd` inference, and title-only matching.
- **Central `ManagedWorkspaceGuard` & Process-Level Agent Write Confinement**: Introduce `ManagedWorkspaceGuard` for application policy authorization AND require an OS/process-level write confinement boundary (e.g. sandbox allow-lists, mount namespaces, or file permissions) preventing executing agent processes from writing `RUNTIME` or any path outside their assigned worktree, even if the agent explicitly attempts to escape (`cd /opt/minime/app && touch x`, absolute path writes, or symlinks).
- **Durable Worktree Ownership & Safe Reconciliation**: Store authoritative worktree ownership in durable database storage outside the mutable worktree (`project_id`, `job_id`, `run_id`, `change_name`, `canonical_worktree_path`, `source_repository_identity`, `source_base_sha`, `branch`, `creation_state`). Require 4-way reconciliation (durable DB record, canonical path, Git `worktree list` observation, and optional filesystem marker) for deletion or partial worktree recovery. Disallow deletion based solely on a mutable in-tree file or path globbing.
- **Runtime Immutability & Deployment Authority Boundary**: Enforce absolute immutability of the deployed runtime checkout for SDLC operations. Separate SDLC workspace mutation authority (`ManagedWorkspaceGuard`) from `DeploymentAuthority`, ensuring SDLC callers cannot escalate to deployment authority or grant managed repository semantics to `RUNTIME`.
- **Normalized Git Identity Verification**: Separate Git remote alias (`remote_name = "origin"`) from normalized repository identity (`canonical_repository_identity`), verifying remotes fail-closed across equivalent URL formats (`git@github.com:...` vs `https://github.com/...`).
- **Legacy Reconciliation & Admission Fence**: Block fresh execution admission if project binding is missing, if runtime aliases managed repository, or if repo remote identity is unverified.
- **Fail-Closed Workspace Semantics**: Classify workspace identity failures, path escapes, or remote mismatches using Stage B typed outcomes (`FAILURE` / `POLICY_DENIED`, `UNKNOWN` / `EVIDENCE_INSUFFICIENT`, `FAILURE` / `CONFLICT`).

## Capabilities

### New Capability: Managed Repository Runtime Isolation
Provides verifiable logical and physical separation between mini me's deployed runtime environment, managed project repositories, and ephemeral execution worktrees, enforcing process-level agent write confinement, central mutation policy authorization, and durable worktree ownership across all single-project and self-hosting operations.
