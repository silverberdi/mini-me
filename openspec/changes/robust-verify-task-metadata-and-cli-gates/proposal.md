## Why

Issue #454 documents three observed failures in the same execution handoff: Verify dispatch leaves the CLI action ambiguous, harmless task annotations invalidate the stored feasibility check, and `minime request ack` can pass a Typer `OptionInfo` into request validation. Together these prevent the verified candidate or an authorized human acknowledgement from progressing through the existing workflow.

## What Changes

- Make the Verify dispatch instructions distinguish the installed native OpenSpec Verify workflow from structural CLI validation. State that `openspec validate --type change --strict <change>` is the CLI validation and that `openspec verify` is not a CLI command; keep provider-specific native workflow dispatch unchanged.
- Compare assessed tasks by their canonical task IDs and a narrowly normalized description: ignore surrounding/redundant whitespace and only the recognized leading status tags named in the Issue (`[DIFERIDA]`, `[DEFERRED]`, `[OPTIONAL]`). Continue to block missing, extra, renamed, or substantively changed tasks; preserve strict checkbox completion and scenario-evidence checks.
- Make `minime request ack <project_id>` forward `operator_response=None` explicitly through the existing request path, retaining the current gate validation, authorization, and durable action behavior.
- Add focused regression coverage for the Verify prompt, cosmetic task metadata, and the CLI acknowledgement command; update both installed Verify skill locations while preserving provider-specific instructions.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `openspec-native-apply-and-verify`: clarify CLI validation instructions while retaining native Verify dispatch by the configured implementer.
- `openspec-native-propose`: preserve feasibility assessment across cosmetic task metadata without weakening task identity or evidence checks.
- `two-phase-pr-and-closure`: make the existing high-complexity acknowledgement available through the CLI without changing its authorization semantics.

## Impact

The change is limited to the Verify prompt and its two installed skills, stage-feasibility task comparison in `orchestration_coordinator.py`, the `request_ack_cmd` forwarding in `cli/main.py`, and focused tests. It adds no endpoint, dependency, database state, migration, or deployment behavior and does not replace or emulate any OpenSpec workflow.
