## Why

The #447 report identifies three execution stalls caused by coordinator metadata and handoff mechanics rather than unresolved product decisions: empty stage evidence lists are treated as unmet dependencies, deterministic Sync/Archive runs require a model-authored completion token, and DOC_CLOSING can rerun spec synchronization or reach PR2 without committing an already archived OpenSpec result. These failures interrupt an otherwise authorized delivery and make the human gate unable to resolve the underlying internal condition.

## What Changes

- Treat an empty `evidence_refs` list on a stage precondition as no evidence-backed dependency for that transition; retain fail-closed behavior for non-empty references that are unknown, missing, or unverified and for missing required capabilities.
- Stop requiring the `MINIME_WORKFLOW_RESULT` completion token for native Sync and Archive operations. Preserve process failure, timeout, environment-error, native human-handoff, and observable filesystem checks as advancement guards.
- Keep the native Sync-then-Archive workflow and tell Archive to use the official `--skip-specs` option after successful Sync, preventing a second application of the same delta specs.
- Before DOC_CLOSING advances toward PR2, ensure the observed archived OpenSpec result and any pending `openspec/` changes are committed on the documentation branch; do not treat an existing archive directory alone as proof of a committed candidate.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `openspec-native-propose`: define how empty stage-precondition evidence differs from real missing or unverified dependency evidence.
- `two-phase-pr-and-closure`: define evidence-based success for Sync/Archive without a mandatory completion token, preserve native human handoffs, avoid re-sync during Archive, and require the archived OpenSpec result to be committed before PR2 progression.

## Impact

- `src/minime/services/proposal_feasibility.py` stage dependency checks.
- `src/minime/services/agent_runner.py` workflow handoff policy for Sync and Archive.
- `src/minime/services/orchestration_coordinator.py` Sync/Archive dispatch, archive observation, and documentation-branch commit boundary.
- Focused feasibility, workflow-handoff, and DOC_CLOSING tests. No database schema, API, deployment, or OpenSpec CLI changes are planned.
