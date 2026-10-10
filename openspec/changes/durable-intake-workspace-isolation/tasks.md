# Tasks: Durable Intake Workspace Isolation & Artifact Publication

- [ ] 1. Domain & Persistence Layer: IntakeWorkspaceOwnership <!-- id: 0 -->
  - [ ] 1.1 Add `IntakeWorkspaceOwnership` domain and SQLAlchemy models with unique constraints <!-- id: 1 -->
  - [ ] 1.2 Add Alembic database migration `g02_intake_workspace_isolation.py` <!-- id: 2 -->
  - [ ] 1.3 Implement `PostgresIntakeWorkspaceOwnershipRepository` interface and UnitOfWork integration <!-- id: 3 -->

- [ ] 2. Workspace Topology & Stage C Mutation Authority <!-- id: 4 -->
  - [ ] 2.1 Define canonical physical topology under `<worktree_parent_dir>/intake-workspaces/<project_id>/<workspace_id>` <!-- id: 5 -->
  - [ ] 2.2 Extend `ManagedWorkspaceGuard` to authorize `OPENSPEC_AUTHORING` only for active `IntakeWorkspaceOwnership` paths (`creation_state == ACTIVE`) <!-- id: 6 -->
  - [ ] 2.3 Reject any direct writes to `managed_repository_root` in `OpenSpecGenerator.write_change_to_disk()` <!-- id: 7 -->

- [ ] 3. Extended INTAKE Saga Phases & External Action Reservation <!-- id: 8 -->
  - [ ] 3.1 Update `INTAKE` saga phases in `IntakeService` and `SagaEngine` <!-- id: 9 -->
  - [ ] 3.2 Implement `INTAKE_WORKTREE_CREATE`, `INTAKE_GIT_COMMIT`, and `INTAKE_ARTIFACT_PUBLISH` external actions with observe-before-repeat semantics <!-- id: 10 -->

- [ ] 4. Authoritative Artifact Publication Contract (Compare-And-Swap) <!-- id: 11 -->
  - [ ] 4.1 Implement commit & push of OpenSpec artifacts to canonical remote Git ref `refs/minime/intake/<change_name>` using CAS <!-- id: 12 -->
  - [ ] 4.2 Update `publication_state`, `published_ref`, and `published_sha` on `IntakeWorkspaceOwnership` after observation <!-- id: 13 -->

- [ ] 5. Single Readiness Authority & Discovery Refactoring <!-- id: 14 -->
  - [ ] 5.1 Update `ReadinessService` to evaluate DoR ONLY against verified published Git refs (`published_ref`) for scheduler admission <!-- id: 15 -->
  - [ ] 5.2 Implement `PublishedIntakeArtifactSource` in `DiscoveryService` to discover published changes without checking out uncommitted files into managed base <!-- id: 16 -->

- [ ] 6. Execution Handoff & Main-Advancement Materialization <!-- id: 17 -->
  - [ ] 6.1 Implement main-advancement pre-admission reconciliation (re-authoring/materializing candidate P2 onto current main B) <!-- id: 18 -->
  - [ ] 6.2 Update execution worktree creation (`OrchestrationWorktreeOwnership`) to materialize OpenSpec artifact tree from `published_sha` onto base `B` <!-- id: 19 -->

- [ ] 7. 4-Way Cleanup Protocol & Legacy Adoption <!-- id: 20 -->
  - [ ] 7.1 Implement 4-way fenced cleanup for intake workspaces authorized ONLY when `creation_state` is `RELEASED_PENDING_CLEANUP` or `FAILED_PENDING_CLEANUP` <!-- id: 21 -->
  - [ ] 7.2 Implement read-only legacy artifact attribution check and adoption into a new owned workspace (`PROVABLE_LEGACY_ARTIFACT` vs `AMBIGUOUS_LEGACY_ARTIFACT` -> `NEEDS_HUMAN`) <!-- id: 22 -->
  - [ ] 7.3 Implement comprehensive unit and integration test suite covering all synchronized contract test scenarios <!-- id: 23 -->
