## Why

Issue #448 reports two observable ways a production run can become unusable: Linux Bubblewrap clients cannot create temporary IPC/build files, and a scheduler restart can leave an incomplete stage invocation that remains blocked even when its recorded process belongs to a previous boot. Both failures prevent the same authorized candidate from progressing safely through agent execution.

## What Changes

- Give each Linux Bubblewrap invocation a private, writable, ephemeral `/tmp` while preserving read-only host mounts and the existing worktree write boundary.
- Prevent persistent .NET/MSBuild build servers from surviving confined invocations through the standard executor environment setting requested in the Issue.
- Allow an incomplete stage invocation to recover after a restart only when the exact candidate is unchanged and recorded process/boot evidence proves the prior coordinator and workflow process group are gone. Record the abandonment, then use the existing fenced claim flow to continue; retain fail-closed behavior for live or unknown process identity.
- Verify the sandbox behavior and durable PostgreSQL recovery with tests against real Bubblewrap and a disposable test database; introduce no parallel recovery table or daemon.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `managed-repository-runtime-isolation`: Define private temporary filesystem behavior as part of the existing process confinement boundary.
- `scheduler-and-recovery-convergence`: Define safe recovery of incomplete stage invocations after a scheduler/host restart.

## Impact

Expected code impact is limited to `src/minime/services/agent_confinement.py` and `src/minime/services/orchestration_coordinator.py`, their executor environment construction, and focused confinement/PostgreSQL integration tests. The existing `orchestration_stage_events` journal and fenced claims remain authoritative; no new table, scheduler, deployment workflow, or production operation is introduced. PR #449 was closed unmerged as an experimental partial implementation, so its code and test claims are not treated as evidence or as the approved design.
