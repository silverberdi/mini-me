## Why

Issue #517 reports three failures at the boundary between managed worktrees and test execution: an interrupted DOC_CLOSING attempt can leave dirty files that prevent recovery, a new worktree may lack already-installed frontend dependencies, and residual active test runs can make the project pause/resume E2E nondeterministic. Together these leave valid work blocked or make its verification unreliable.

## What Changes

- Persist durable ownership for a DOC_CLOSING worktree in the existing ownership registry before creating or reusing it; recover an abandoned worktree only after the existing process-absence and durable-claim checks prove a safe successor, restore that exactly owned worktree to `HEAD` before computing the retry fingerprint, and replay native SYNC before ARCHIVE when that reset removed uncommitted sync effects.
- Reuse valid root or `frontend/` `node_modules` already present in the registered base repository when creating a matching worktree, without network installation; ensure dependency links remain ignored and absent from candidate commits.
- Make the Playwright project-state reset deterministic for the E2E test project: clear only residual test runs in the test database, surface cleanup failures, and verify immediate pause/resume behavior without changing production project endpoints.
- Keep existing distributed claim, fencing, human-authorization, and process-confinement semantics. A proven-absent process does not authorize bypassing a still-active durable claim; recovery waits until the existing claim mechanism permits safe replacement.

## Capabilities

### New Capabilities

- `playwright-project-fixture-isolation`: deterministic cleanup and lifecycle setup for the Playwright test project only.

### Modified Capabilities

- `scheduler-and-recovery-convergence`: safely recover a dirty DOC_CLOSING worktree from an abandoned invocation without weakening claim or fencing rules.
- `autonomous-worktree-startup`: provide already-installed root/frontend dependencies to matching new worktrees without including them in Git candidates.

## Impact

- Backend: `NativeOrchestrationCoordinator` DOC_CLOSING stage-invocation recovery and `WorktreeManager.create_worktree`.
- Test tooling: Playwright `resetProjectState` and its project pause/resume E2E coverage; cleanup is restricted to the configured disposable E2E database and `e2e-project` fixture.
- Git hygiene: dependency-link paths must be ignored and must not enter the Git index or candidate commits.
- No production API contract, provider role, deployment workflow, distributed claim semantics, process confinement, or operator authorization policy changes.
