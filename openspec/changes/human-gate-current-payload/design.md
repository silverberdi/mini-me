## Context

See `proposal.md` for the reported behavior and scope. On the current `origin/main` candidate, `OrchestrationRunModel` already stores `stop_details` as PostgreSQL JSON. Gate production is in `src/minime/services/orchestration_coordinator.py`; `GET /api/v1/orchestration/runs` in `src/minime/api/app.py` currently falls back from the top-level payload to Explore/Propose checkpoints and copies that value only when the top-level key is absent. The Trabajo actual component also falls back to `human_request` and `metadata.human_payload`. This permits a resolved checkpoint to supply the question for a later gate. The PR1 acknowledgement currently returns a payload without persisting it, while Apply escalation and code-review escalation do not consistently persist a current payload.

The existing operator response endpoint and form remain the authority for answers. The human gate itself remains in place.

## Goals / Non-Goals

**Goals:**

- Give each scoped gate a durable question/options payload and replace the active payload on gate transition.
- Make the Run projection and Trabajo actual use the active gate payload only.
- Preserve the existing operator response path and gate authorization.

**Non-Goals:**

- Redesigning the human-attention inbox or changing which decisions require a person.
- Changing other workflow stages, response semantics, or authorization policy.
- Adding a payload table, new gate state machine, schema migration, or synthetic choices.

## Decisions

### Store one active payload in the existing Run record

Use the existing `stop_details` JSON field and its top-level `human_payload` as the canonical payload for the unresolved gate. Gate writers replace that value when review escalation, Apply escalation, PR1 acknowledgement, or physical validation becomes active, and persist it in the same durable Run update as the gate state. Include the gate/stage identity, a question, and an `options` collection. Preserve option content from the current gate; do not attribute generated suggestions to OpenSpec. Where a gate supplies no choices, keep the collection empty and retain the existing free-text response control rather than inventing decisions.

This reuses the current persistence model and avoids a second authority or migration. A separate table or append-only gate history is unnecessary for the Issue's requirement; existing run/checkpoint history remains intact.

### Normalize all scoped gate writers at the transition boundary

Update the existing proposal/code-review escalation paths and `_escalate_apply_to_human` so they persist the payload that belongs to the gate being entered. The physical-validation path uses the same Apply escalation route but supplies its own current question and gate identity. Persist the PR1 acknowledgement payload before returning the HUMAN_REQUIRED result. When a gate is durably resolved, remove its active payload as part of the existing state update; a subsequent gate writes its own payload. Do not alter the gate decision, merge policy, or response authorization.

### Project and render only current durable authority

For the run-list API, take the human payload from the active top-level Run field only. Do not reconstruct a current request from resolved Explore/Propose checkpoints. The frontend gate detection, question, and options selectors in Trabajo actual read that same canonical payload, not `human_request` or generic Run metadata. If an active gate lacks a durable payload, do not show a previous question as a substitute; keep the unresolved state visible with the existing unavailable-context treatment and preserve the response control only where the backend authorizes it.

The Dashboard remains a notification/navigation surface. The existing response submission and refresh behavior remain unchanged and continue to show resolution only after durable backend confirmation.

### Validate the gate-to-UI path with focused evidence

Add coordinator tests for each scoped writer and replacement of an existing payload, API tests proving stale nested checkpoints are not projected as current, and frontend coverage that a later gate's question/options render after refresh and can use the existing response action. Include an integration path using persisted Run state and the real API/PWA wiring; mocks may cover isolated boundaries but do not stand in for that path.

## Risks / Trade-offs

- [Older unresolved Runs may lack a top-level payload] → Never restore a resolved nested question; display the unresolved gate without stale content and retain the currently authorized response route.
- [Gate writers may update payload and gate status separately] → Persist them in the same existing Run update/transaction and test the stored result for every scoped gate.
- [Some gates have no enumerated choices] → Always provide the `options` collection, preserve any choices the gate actually supplies, and retain free-text response where it supplies none; do not invent gate decisions.

## Migration Plan

No database migration is needed because `orchestration_runs.stop_details` already stores JSON. Deploy the backend writer/projection changes with the PWA selector changes. Rollback is a code rollback; no persisted-data conversion is required. Runs created after the change use the current-payload contract; existing historical checkpoints are left untouched and are not promoted to active payloads.
