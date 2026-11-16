## Why

Mini Me can accept a strictly valid OpenSpec proposal whose tasks cannot be completed with the configured agents, available integrations, or authorized workflow—for example, validating a candidate that cannot be deployed to preview before merge. That sends work into Apply with no executable path, wastes attempts, and creates a human gate after the proposal should have been stopped.

## What Changes

- Add an execution-feasibility decision after native Propose and strict validation, before proposal acceptance and Apply.
- Require evidence for every task that identifies its execution stage, responsible actor, capability, dependencies needed before that stage, and observable completion evidence.
- Evaluate blockers at the transition that needs them: do not require Apply outputs before Apply, and do not block Apply on dependencies for Verify or later stages. Keep later work pending and fail closed before the stage that needs a missing dependency; reject proposals whose mandatory work has no authorized path in any stage.
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
