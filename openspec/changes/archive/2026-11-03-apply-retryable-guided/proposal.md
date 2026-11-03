## Why

Issue #259 documents a partial Apply that left substantial implementation in the candidate but was retried without useful direction, causing repeated work and operator intervention. mini me needs to recover from observable partial progress while preserving the native OpenSpec workflow and candidate identity.

## What Changes

- Make Apply outcomes structured and evidence-backed so partial completion, human questions, and terminal failures are handled distinctly.
- Guide bounded Apply retries with observed candidate, task, Git, and test state; stop on lack of progress or regression.
- Verify recovery deterministically with a simulated partial Apply.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `openspec-native-apply-and-verify`: define evidence-backed partial Apply recovery, retry limits, regression handling, and Verify readiness.

## Impact

Apply orchestration and its callers, candidate Git/test evidence capture, retry context and limits, and deterministic orchestration tests. No new provider, workflow, or persistence entity is proposed.
