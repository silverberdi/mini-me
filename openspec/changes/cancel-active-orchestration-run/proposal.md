## Why

An active Mini Me Run can remain in `HUMAN_REQUIRED` after the operator decides to stop it, keeping the project's single active Run slot occupied. Today there is no supported cancellation operation, so operators cannot safely release that slot through the API, CLI, or PWA.

## What Changes

- Add an authenticated, Run-targeted cancellation operation for a stopped human gate with no active stage job.
- Record `CANCELLED`, clear the human gate, mark the Run inactive, and preserve existing stop details while adding cancellation actor, reason, and time.
- Expose the operation through the API, CLI, and the current Run view; reject stale, terminal, or actively executing Runs without changing their state.
- Reuse existing worktree ownership and cleanup behavior after the terminal transition; never update PostgreSQL directly outside repositories.
- Keep `request complete` semantics unchanged.

## Capabilities

### New Capabilities

- `run-cancellation`: Explicit, audited cancellation of an active human-gated orchestration Run through supported interfaces.

### Modified Capabilities

- None.

## Impact

- API: authenticated cancellation endpoint scoped to project and Run identity.
- CLI: `request cancel` command targeting the active Run.
- PWA: cancellation control on an eligible human-gated Run with confirmation and visible failure feedback.
- Domain/service/repository lifecycle for atomic terminal transition and active-slot release; reuse existing worktree cleanup.
- Tests: service/API/CLI/UI coverage and PostgreSQL integration proof that cancellation releases the active Run slot exactly once.
