## Why

After a human-authorized native OpenSpec Update is strictly validated, Apply still compares its result against the pre-Update task snapshot. A legitimate reclassification of published-version evidence as pending for the current candidate is therefore reported as candidate regression, blocking the same Run despite an unchanged candidate identity.

## What Changes

- Bind the validated Update result to the exact affected task dispositions and the existing Run, Change, branch, worktree, and candidate identity.
- Reconcile Apply's progress comparison for only the criteria whose disposition was changed by that authorized Update.
- Preserve regression checks for candidate identity, changed files, test results, and every criterion outside the validated reclassification; retain all prior attempts and evidence.
- Keep replay and restart behavior idempotent and fail closed when Update provenance, strict validation, affected tasks, or candidate identity is ambiguous.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `openspec-native-apply-and-verify`: distinguish an authorized task/evidence reclassification from regression while retaining fail-closed recovery checks.
- `openspec-orchestration-continuity`: durably bind the validated Update and the narrowly adjusted recovery comparison to the same candidate and operator action.

## Impact

- `src/minime/services/orchestration_coordinator.py` Apply recovery snapshot and validated gate-Update checkpoint.
- Focused Apply-reentry tests and PostgreSQL-backed response → native Update → Apply E2E coverage.
- No new API, provider, retry limit, database entity, or migration is intended; confirm persistence can use the existing durable checkpoint during design.
