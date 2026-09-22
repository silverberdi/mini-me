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
- Managed project OpenSpec artifacts (`Project OpenSpec Workspace`)

## What Changes

- **Strict Workspace Model**: Explicitly separate `RUNTIME`, `MANAGED_REPOSITORY`, `EXECUTION_WORKTREE`, and `PROJECT_OPENSPEC_WORKSPACE` identities across all services.
- **Self-Hosting Isolation Guarantee**: Require that when mini me manages its own repository (`mini-me`), the deployed runtime checkout (`/opt/minime/app` or equivalent) and the managed project repository (`<managed-root>/mini-me/repository`) remain strictly separate physical and logical identities. SHA equality does NOT collapse workspace identity.
- **Project Managed Repository Binding**: Define `ProjectManagedRepositoryBinding` carrying `project_id`, `repository_url`, `managed_repository_root`, `default_base_branch`, `canonical_git_remote`, `workspace_role`, and ownership markers. Require verified binding lookup; forbid path guessing, `cwd` inference, and title-only matching.
- **Central `ManagedWorkspaceGuard`**: Introduce a single, authoritative mutation guard (`ManagedWorkspaceGuard`) that validates workspace role, filesystem path canonicalization, trusted-root containment, Git repository remote identity, and operation permissions before ANY filesystem side effect is permitted.
- **Runtime Immutability**: Enforce absolute immutability of the deployed runtime checkout for SDLC operations (no agent code edits, no branch manipulation, no OpenSpec sync/archive, no worktree creation).
- **Explicit Deployment Boundary**: Define the deployment boundary as an explicit, unidirectional promotion of verified candidate commits (`managed repo candidate -> explicit deploy process -> runtime artifact`), which never grants managed workspace semantics to the runtime.
- **Git & Worktree Ownership Verification**: Require explicit verification of Git remote identity, root path, and worktree metadata (`project_id`, `job_id`, `run_id`, `change_name`, `branch`) before creating, modifying, or cleaning up worktrees. Forbid ambiguous glob deletions.
- **Legacy Reconciliation & Admission Fence**: Block fresh execution admission if project binding is missing, if runtime aliases managed repository, or if repo remote identity is unverified.
- **Fail-Closed Workspace Semantics**: Classify workspace identity failures, path escapes, or remote mismatches using Stage B typed outcomes (`FAILURE` / `POLICY_DENIED`, `UNKNOWN` / `EVIDENCE_INSUFFICIENT`, `FAILURE` / `CONFLICT`).

## Capabilities

### New Capability: Managed Repository Runtime Isolation
Provides verifiable logical and physical separation between mini me's deployed runtime environment, managed project repositories, ephemeral execution worktrees, and project OpenSpec artifacts, enforcing central mutation authorization and preventing runtime workspace aliasing across all single-project and self-hosting operations.
