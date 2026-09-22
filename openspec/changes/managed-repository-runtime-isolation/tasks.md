# Tasks: Managed Repository Runtime Isolation

## Task Plan

- [ ] 1. Complete comprehensive codebase inventory of all active filesystem and Git repository writers (`cwd` readers, `WorktreeManager`, `OpenSpecSyncService`, `OpenSpecArchiveService`, `OrchestrationService`, implementer/reviewer runners, cleanup routines, and onboarding handlers).
- [ ] 2. Define domain models for workspace isolation: `WorkspaceRole` enum (`RUNTIME`, `MANAGED_REPOSITORY`, `EXECUTION_WORKTREE`, `UNKNOWN`), `ProjectManagedRepositoryBinding`, `WorkspaceMutationRequest`, `WorkspaceMutationDecision`, and `WorktreeOwnershipMetadata` in `src/minime/domain/models.py` and `enums.py`.
- [ ] 3. Implement durable storage and repository support for `ProjectManagedRepositoryBinding` in `src/minime/db/repository.py` and SQLAlchemy schemas, enforcing unique project-to-repository-root bindings.
- [ ] 4. Implement central `ManagedWorkspaceGuard` (or `WorkspaceMutationAuthority`) providing single-point authorization for all filesystem and Git side effects across mini me.
- [ ] 5. Implement strict path canonicalization, symlink resolution (`os.path.realpath`), `..` path traversal rejection, and trusted managed-root containment checks in `ManagedWorkspaceGuard`.
- [ ] 6. Implement fail-closed Git identity verification in `ManagedWorkspaceGuard` (`git rev-parse --show-toplevel`, `git remote get-url origin`, and `.minime-managed-project.json` ownership marker verification).
- [ ] 7. Migrate `WorktreeManager` to require explicit worktree metadata files (`.minime-worktree.json`) on creation and enforce `ManagedWorkspaceGuard` authorization before writing.
- [ ] 8. Migrate orchestration setup, primary implementer runner, and auditor reviewer runner to resolve execution paths strictly within authorized `EXECUTION_WORKTREE` directories.
- [ ] 9. Migrate `OpenSpecSyncService` and `OpenSpecArchiveService` to resolve change and spec target paths strictly against `MANAGED_REPOSITORY` or `EXECUTION_WORKTREE`, blocking operations on `RUNTIME`.
- [ ] 10. Migrate post-merge cleanup and process restart recovery to verify `.minime-worktree.json` ownership before deleting directories, skipping unowned or ambiguous folders.
- [ ] 11. Migrate project onboarding and bootstrap handlers (`ProjectOnboardingService`) to establish isolated `MANAGED_REPOSITORY` directories under the configured trusted root and reject `RUNTIME` path collision.
- [ ] 12. Implement legacy aliasing detection and reconciliation logic blocking fresh work admission when `RUNTIME` aliases `MANAGED_REPOSITORY` until separate managed root is bound.
- [ ] 13. Implement admission fence in `ReadinessService` and `IntakeService` blocking transition to `IN_PROGRESS` if project binding is unverified, remote mismatches exist, or workspace isolation is unproven.
- [ ] 14. Instrument observability telemetry and status endpoints exposing `is_runtime_isolated`, managed repository HEAD SHA, active worktree counts, and `workspace_mutation_denied_total` metrics.
- [ ] 15. Add exhaustive adversarial unit and integration tests covering all 18 design scenarios (`RUNTIME` collision, symlink escapes, remote mismatches, self-hosting isolation, partial worktree recovery, unowned cleanup, etc.).
- [ ] 16. Perform exhaustive codebase audit verifying no active writer mutates runtime or project paths without explicit `ManagedWorkspaceGuard` authorization, followed by Ruff linting and pytest suite verification.
