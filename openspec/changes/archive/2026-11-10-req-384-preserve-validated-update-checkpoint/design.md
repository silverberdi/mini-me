## Context

See `proposal.md` for the production evidence. Apply-exhaustion gate responses currently enter the same native Update path as criterion-disposition responses. A continuation-only response therefore creates a validated no-op Update and overwrites the prior checkpoint containing the authorized task reclassification.

## Goals / Non-Goals

**Goals:** Separate continuation from disposition changes and keep the existing validated checkpoint available to the following Apply cycle on the same candidate.

**Non-Goals:** Change provider behavior, candidate identity rules, retry limits, criterion dispositions, or database schema.

## Decisions

- Only gates that request a criterion disposition change dispatch native OpenSpec Update. A response to an Apply exhaustion/retry gate authorizes another Apply cycle directly.
- Resolve the reclassification exception set from the latest durable `VALIDATED` checkpoint for the active Run, Change, branch, worktree, generation, and candidate SHA. The checkpoint remains tied to the original operator action; a later retry action does not replace that provenance.
- Preserve the existing strict fail-closed checks for identity, files, tests, and task losses outside the checkpoint's exact reclassified task IDs.
- Extend coordinator tests and PostgreSQL E2E to reproduce the observed sequence: validated reclassification, partial Apply, continuation-only response, and another Apply without losing the checkpoint.

## Risks / Trade-offs

- **Risk:** Reusing a stale checkpoint could mask a real regression. **Mitigation:** Require an exact identity and SHA match and use only task IDs recorded by the strictly validated Update.
- **Risk:** A criterion change could be misread as a continuation. **Mitigation:** Disposition changes remain routed through the explicit Update gate; ambiguous responses stay human-required and do not dispatch Apply.

## Migration Plan

No database migration is expected. Existing checkpoints lacking exact identity or validated disposition evidence are ignored and retain current fail-closed behavior. Deployment remains the project's CI/CD responsibility.
