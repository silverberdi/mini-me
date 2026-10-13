## ADDED Requirements

### Requirement: Safe AUTH_REQUIRED recovery of an existing worktree
The system SHALL reuse or recreate a worktree only when durable ownership, canonical repository identity, project/change/run/job identity, branch/base lineage, recovery snapshot, Git registration, and allowed artifact state agree. An AUTH_REQUIRED outcome SHALL NOT independently authorize worktree recovery. It MAY authorize reuse only for a physically present worktree with ownership CREATED when the uniquely identified latest attempt and complete attempt history prove no material progress, no candidate exists, an exact current Control Plane continuation claim is fenced and active, no unresolved external action exists, and every existing repository, snapshot, path, Git, and published-artifact check succeeds. This exception SHALL NOT authorize recreation of a physically absent DELETED worktree.

#### Scenario: Existing CREATED worktree resumes after authentication failure
- **GIVEN** the same linked Run and Job have contiguous durable attempts ending in a unique completed AUTH_REQUIRED attempt with no material progress or candidate
- **AND** ownership is CREATED and the original snapshot, branch, canonical path, repository binding, and published artifacts verify
- **AND** a current CONTROL_PLANE DRIVE_CONTINUATION decision has a live matching claim fence
- **WHEN** the authorized continuation requests reuse of the existing worktree
- **THEN** the same worktree is reused with its original branch, base, snapshot, Run, Job, attempts, and counters preserved
- **AND** validation continues through all existing Git, ownership, remote-base, and artifact checks before execution can reach the runner

#### Scenario: AUTH_REQUIRED cannot recreate a DELETED worktree
- **GIVEN** ownership is DELETED and the worktree directory is absent
- **AND** the latest attempt is AUTH_REQUIRED
- **WHEN** continuation requests worktree recovery
- **THEN** recovery is rejected unless the unchanged pre-existing DELETED recovery policy independently authorizes it

#### Scenario: Progress or inconsistent attempt history blocks CREATED reuse
- **GIVEN** ownership is CREATED but attempts are missing, duplicated, non-contiguous, inconsistent with the Job counter, or show material progress, same-SHA suppression, or a candidate
- **WHEN** continuation requests worktree reuse after AUTH_REQUIRED
- **THEN** recovery fails closed without changing durable history or the worktree

#### Scenario: Missing or stale continuation authority blocks CREATED reuse
- **GIVEN** ownership is CREATED and attempts otherwise qualify
- **BUT** the current decision is not an exact CONTROL_PLANE DRIVE_CONTINUATION with the live Run claim fence, or an external action is pending or ambiguous
- **WHEN** continuation requests worktree reuse
- **THEN** recovery fails closed without starting a provider or modifying Run/Job history
