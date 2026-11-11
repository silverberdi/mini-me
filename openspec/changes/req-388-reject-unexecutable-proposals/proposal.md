## Why

Mini Me can accept a strictly valid OpenSpec proposal whose tasks cannot be completed with the configured agents, available integrations, or authorized workflow—for example, validating a candidate that cannot be deployed to preview before merge. That sends work into Apply with no executable path, wastes attempts, and creates a human gate after the proposal should have been stopped.

## What Changes

- Add an execution-feasibility decision after native Propose and strict validation, before proposal acceptance and Apply.
- Require evidence for every task that identifies its responsible actor, available capability, required preconditions, and observable completion evidence.
- Keep the proposal unaccepted and fail closed when any task depends on an unavailable deployment, physical test, external participant, or other unconfirmed capability; show the specific blocker and what must change before re-evaluation.
- Preserve the boundary that deployment belongs to project CI/CD; do not add a deployment mechanism to Mini Me or infer that a deployment will happen.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `openspec-native-propose`: require evidence-backed feasibility of every proposed task before a Change can advance to Apply.

## Impact

- Orchestration proposal/readiness flow and its existing PostgreSQL human-gate evidence.
- Configured provider/tool capability evidence and repository workflow inspection; no new provider role, service, deployment mechanism, or database table.
- PostgreSQL/API/coordinator tests proving a feasible proposal advances and an unexecutable or unsubstantiated proposal remains unaccepted without starting Apply.
