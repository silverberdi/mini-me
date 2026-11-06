## Why

The strict OpenSpec validator currently rejects 16 main specifications, so those entries are parsed incompletely or cannot be reliably validated. This change reconciles their document structure using the source and history that already exist, without changing product behavior.

## What Changes

- Normalize the 16 failing main specs to the canonical OpenSpec spec structure.
- Trace each normalization to its existing content, archived change, or Git history; record unresolved intent gaps instead of inferring requirements.
- Validate each affected spec and rerun the global spec validation, reporting any remaining baseline failures.

## Capabilities

### New Capabilities

None. This is documentation-format reconciliation and introduces no product behavior.

### Modified Capabilities

None. No behavioral requirements change; this change opts out of delta specs with `skip_specs: true`.

## Impact

- OpenSpec documentation only: the 16 main spec files named in Issue #309 and this change's planning artifacts.
- No source code, tests, API, database, runtime behavior, or dependencies.
- Validation evidence: per-spec strict validation and `openspec validate --specs`, compared with the clean-worktree baseline of 85 passing and 16 failing specs (101 total) at `8d26b89011f50953acbeef7f33b34fda2a29c2db`.
