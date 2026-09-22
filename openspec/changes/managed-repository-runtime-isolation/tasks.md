# Tasks: Managed Repository Runtime Isolation

## Task Plan

- [ ] 1. Complete comprehensive codebase inventory of all active filesystem and Git repository writers (`cwd` readers, `WorktreeManager`, `OpenSpecSyncService`, `OpenSpecArchiveService`, `OrchestrationService`, implementer/reviewer runners, cleanup routines, and onboarding handlers).
- [ ] 2. Define domain models for workspace isolation: `WorkspaceRole` enum (`RUNTIME`, `MANAGED_REPOSITORY`, `EXECUTION_WORKTREE`, `UNKNOWN`), `ProjectManagedRepositoryBinding` (with `remote_name` and normalized `canonical_repository_identity`), `WorkspaceMutationRequest`, `WorkspaceMutationDecision`, and `OrchestrationWorktreeOwnership` in `src/minime/domain/models.py` and `enums.py`.
- [ ] 3. Implement durable storage and repository support for `ProjectManagedRepositoryBinding` and `OrchestrationWorktreeOwnership` in `src/minime/db/repository.py` and SQLAlchemy schemas, enforcing durable DB worktree ownership records outside the mutable worktree.
- [ ] 4. Implement central `ManagedWorkspaceGuard` providing single-point policy authorization for all SDLC filesystem and Git side effects across mini me.
- [ ] 5. Implement strict path canonicalization, symlink resolution (`os.path.realpath`), `..` path traversal rejection, and trusted managed-root containment checks in `ManagedWorkspaceGuard`.
- [ ] 6. Implement fail-closed Git remote identity verification in `ManagedWorkspaceGuard` (`git remote get-url <remote_name>` compared against normalized `canonical_repository_identity`, and `.minime-managed-project.json` ownership marker verification).
- [ ] 7. Implement OS/process-level write confinement boundary wrappers (sandbox write allow-lists, mount namespaces, or file permissions) in implementer and reviewer runners, ensuring executing agent processes cannot write `RUNTIME` or paths outside their assigned worktree.
- [ ] 8. Migrate `WorktreeManager` to write durable `OrchestrationWorktreeOwnership` DB records on creation and enforce `ManagedWorkspaceGuard` authorization before writing.
- [ ] 9. Migrate orchestration setup, primary implementer runner, and auditor reviewer runner to resolve execution paths strictly within authorized `EXECUTION_WORKTREE` directories under process write confinement.
- [ ] 10. Migrate `OpenSpecSyncService` and `OpenSpecArchiveService` to resolve change and spec target paths strictly against `MANAGED_REPOSITORY` or `EXECUTION_WORKTREE`, blocking operations on `RUNTIME`.
- [ ] 11. Implement 4-way worktree cleanup reconciliation (durable DB record, canonical path, Git `worktree list` observation, and marker), rejecting deletion based solely on in-tree markers or folder globs.
- [ ] 12. Implement partial worktree recovery protocol requiring durable pre-creation DB record (`creation_state = "PENDING"`) to authorize directory pruning, preserving un-tracked folders for operator review (`NEEDS_HUMAN`).
- [ ] 13. Formalize `DeploymentAuthority` boundary separating production deployment pipelines from `ManagedWorkspaceGuard` SDLC mutation authority, blocking SDLC caller escalation.
- [ ] 14. Migrate project onboarding and bootstrap handlers (`ProjectOnboardingService`) to establish isolated `MANAGED_REPOSITORY` directories under the configured trusted root and reject `RUNTIME` path collision.
- [ ] 15. Implement legacy aliasing detection and reconciliation logic blocking fresh work admission when `RUNTIME` aliases `MANAGED_REPOSITORY` until separate managed root is bound.
- [ ] 16. Implement admission fence in `ReadinessService` and `IntakeService` blocking transition to `IN_PROGRESS` if project binding is unverified, remote mismatches exist, process write confinement is unverified, or workspace isolation is unproven.
- [ ] 17. Instrument observability telemetry and status endpoints exposing `is_runtime_isolated`, `is_agent_confinement_active`, managed repository HEAD SHA, active worktree counts, and `workspace_mutation_denied_total` metrics.
- [ ] 18. Add exhaustive adversarial unit and integration tests covering all 21 design scenarios (`RUNTIME` collision, agent shell write escape `cd /opt/minime/app && touch x`, absolute path write, symlink escape into runtime, spoofed marker, partial recovery with/without DB record, remote identity normalization, self-hosting isolation, etc.).
- [ ] 19. Perform exhaustive codebase audit verifying no active writer mutates runtime or project paths without explicit `ManagedWorkspaceGuard` authorization and process write confinement, followed by Ruff linting and pytest suite verification.
