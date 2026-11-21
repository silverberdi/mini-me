## Context

Issue #454 identifies three defects in existing workflow boundaries: the Verify prompt does not distinguish native workflow dispatch from CLI validation; stage feasibility hashes task text verbatim and treats approved status annotations as substantive edits; and `request ack` omits an explicit nullable response when delegating to the shared request command. The relevant consumers are `_run_verify`, `_check_stage_feasibility`, `request_ack_cmd`, the existing Verify skill files, and their focused tests. No API, database schema, deployment, or OpenSpec workflow implementation is needed.

The feasibility assessment currently persists `source_text_sha256` but not the assessed task text. Therefore, normalizing only the current description cannot safely establish that a changed legacy task is equivalent. The recorded `candidate_sha` is the existing provenance anchor for resolving this compatibility case.

## Goals / Non-Goals

**Goals**
- Make Verify instructions accurately distinguish the provider-native OpenSpec workflow from `openspec validate --type change --strict`.
- Ignore only the specifically approved cosmetic task annotations while preserving task identity, substantive-content, completion, and evidence checks.
- Make the existing CLI acknowledgement call the same validation and durable action path as other operator acknowledgements.

**Non-Goals**
- Adding or emulating an OpenSpec `verify` CLI command or changing provider workflow dispatch.
- Weakening fail-closed feasibility checks, changing stage policy, or accepting arbitrary task edits.
- Adding persistence tables, migrations, endpoints, new gate types, or a second acknowledgement path.
- Changing deployment or merge policy.

## Decisions

### 1. Keep Verify execution provider-native

Update `_run_verify` prompt wording and both installed Verify skill copies to say that structural validation is performed by `openspec validate --type change --strict <change-name>`, while Verify itself is invoked through the already resolved provider-specific workflow. Explicitly state that `openspec verify` is not a CLI command. Preserve each provider's existing dispatch syntax and do not create a prompt substitute or wrapper.

### 2. Canonicalize task descriptions and preserve assessment provenance

Use the canonical `X.Y` task ID as identity. A small deterministic normalization function should trim and collapse whitespace and remove only recognized status tags `[DIFERIDA]`, `[DEFERRED]`, and `[OPTIONAL]` immediately following the task ID; it must not remove arbitrary bracketed text or alter substantive words. Persist a canonical description digest alongside the existing source digest in the existing JSON assessment record, with no schema migration.

For assessments created before the canonical digest exists, first preserve the current exact-hash comparison. If it differs, resolve the original task inventory from the assessment's recorded candidate revision and compare the recovered task description using the same normalization. If that exact source cannot be recovered, keep the transition blocked with a specific diagnostic; do not guess that the edit was cosmetic. Scenario hashes and all existing checkbox, dependency, completion-evidence, and scenario-coverage checks remain unchanged.

### 3. Forward CLI acknowledgement explicitly through the shared command

Pass `operator_response=None` explicitly in `request_ack_cmd` when it calls `request_run_cmd`. Keep `request_run_cmd` and `prepare_gate_response` as the authority for active-gate validation, authorization, idempotency, and durable recording. Add a focused Typer `CliRunner` regression test that exercises the command boundary and proves the request model receives `None`.

## Risks / Trade-offs

- Recovering a legacy task baseline depends on the recorded candidate revision and the task file being present in that revision. If either is unavailable, fail-closed behavior remains; the diagnostic must make the missing source clear.
- Normalization intentionally recognizes only the three status tags in Issue #454. New tag forms must be explicitly specified rather than accepted by a broad bracket-removal rule.
- The two Verify skill directories have provider-specific differences. Edit both while preserving their respective invocation syntax; do not copy one over the other wholesale.
- Focused tests must exercise task comparison, generated Verify prompt text, and the actual CLI command adapter path, rather than testing helper output alone.

## Migration Plan

No database migration is required. New assessments add a canonical digest to the existing JSON payload. Existing records remain readable through exact-hash comparison and candidate-revision source recovery, with the existing fail-closed path when provenance cannot be recovered.
