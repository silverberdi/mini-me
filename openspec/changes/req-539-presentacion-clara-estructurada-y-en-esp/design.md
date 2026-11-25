# Design

## Context

The existing `pwa-runs-and-pipeline-observability` contract already owns the current Human Gate, its durable payload, the `Trabajo actual` route and the authorized response path. The implementation has backend construction/projection around `NativeOrchestrationCoordinator` and a focused Angular component at `frontend/src/app/features/trabajo-actual/trabajo-actual.component.ts`, with existing unit and Playwright coverage. See `proposal.md` for motivation and the delta spec for observable behavior.

The change must preserve the current gate identity, original workflow wording/options, redaction, optimistic response behavior and terminal-run protections. It is a presentation and payload-shaping change, not a new state machine, persistence model, endpoint, route or translation service.

## Goals / Non-Goals

**Goals:**

- Produce a small, deterministic Spanish presentation model for `proposal_feasibility` and `apply_escalation`.
- Render summary, pending items, options and technical audit as separate visual concerns in Trabajo actual.
- Make legacy payloads safe and readable without requiring a backfill.
- Verify the result with focused unit tests and a real Playwright browser path, including the unchanged response transition.
- Complete a removal ledger for the replaced monolithic gate rendering and keep only one active presentation path.

**Non-Goals:**

- Do not change human authorization, state transitions, action values, endpoint contracts, gate selection or fail-closed rules.
- Do not translate or rewrite the original workflow question/options used by the authority; Spanish explanations are additive presentation fields.
- Do not add a database table, migration, external dependency, provider, route, deployment step or generic i18n framework.
- Do not redesign unrelated Dashboard, Trabajo, Backlog or non-gate stages.

## Decisions

### 1. Enrich the existing payload at its current construction boundary

The coordinator/read path will add the three presentation fields while preserving the raw/current gate data. This keeps the Runs API as the single authority consumed by the existing frontend and avoids a second translation or projection layer. The alternative of deriving all text in Angular was rejected because it would duplicate backend semantics and leave API consumers without the enriched contract. The alternative of introducing a new endpoint was rejected as unnecessary scope.

The enrichment must be bounded to the two authorized gate names and pass through the existing `NativeOrchestrationCoordinator._safe_human_payload` boundary, which delegates recursively to `minime.logging.redact_secrets` before the payload becomes durable or operator-visible. The implementation and focused tests SHALL exercise that boundary explicitly for each new field: `summary_es`, every item in `pending_items`, and every option/description in `options_es`; confidential values in any of those fields must be replaced by the established redaction marker and must not appear in the persisted or Runs projection payload. A parse failure must preserve fail-closed behavior rather than inventing a decision.

### 2. Use a small presentation normalizer with explicit fallback rules

The frontend will prefer `summary_es`, `pending_items` and `options_es`, then use a narrow compatibility helper for legacy semicolon-delimited strings and existing option shapes. The helper will return stable display items, not mutate the durable payload or response values. This is simpler and safer than a general-purpose localization framework.

### 3. Separate action content from technical audit in the component

The card will render the summary and decision controls in the primary surface, pending items as titled warning bullets, and raw diagnostic fields in a native/accessibly labeled disclosure titled `Detalles técnicos y auditoría`. The disclosure is local to the current card, so expansion does not navigate away or lose gate identity. Technical data remains hidden by default.

### 4. Preserve response submission and prove it in the browser

The existing response handler, request identifier/idempotency inputs and refresh/SSE authority remain the only response path. Unit tests cover parsing/render decisions; Playwright uses the configured Chromium runtime against the served application and observes the actual request plus refreshed run state. A mocked DOM-only test cannot satisfy the browser evidence requirement.

### 5. Removal ledger for the replaced presentation

| Replaced behavior | Old entrypoint/consumer | Action | Evidence required |
| --- | --- | --- | --- |
| Monolithic Human Gate paragraph and inline technical dump | Human Gate template/helpers in `trabajo-actual.component.ts` | REMOVE after parity | focused unit tests, Playwright DOM evidence and static search for obsolete rendering branch |
| Existing durable payload fields, response endpoint and audit history | Coordinator, Runs projection, response action path, persisted `stop_details` | RETAIN-WITH-REASON | backend regression tests and browser-observed response transition |

No database or historical audit data is removed. Any legacy parsing fallback remains only while historical payloads without enriched fields are valid consumers; it is a compatibility reader, not a second authority.

## Risks / Trade-offs

- [Risk] Existing payload shapes vary across historical runs. → Prefer enriched fields, normalize null/malformed values defensively, and retain a readable semicolon fallback without mutating durable state.
- [Risk] Technical details could leak into the primary decision surface or expose secrets. → Keep the accordion collapsed, reuse the existing redaction boundary, and assert the primary DOM excludes raw diagnostic content until expansion.
- [Risk] The new Spanish presentation fields could bypass redaction because they are newly constructed after the legacy payload path. → Construct them before `_safe_human_payload` completes, test `summary_es`, `pending_items` and `options_es` with secret-like values individually, and assert both the durable payload and Runs projection contain only the established redacted forms.
- [Risk] A visual refactor could accidentally break response submission. → Keep the current handler and action values unchanged and require a real-browser request/refresh assertion.
- [Risk] Spanish copy could become cryptic or imply an unauthorized decision. → Keep copy action-oriented and explanatory, while preserving original workflow wording/options verbatim and treating any unresolved translation convention as a validation item, not an invented policy.
- [Risk] The change could drift into unrelated UI. → Limit edits and tests to the existing Human Gate payload/projection and `frontend/src/app/features/trabajo-actual/` surfaces.

## Migration Plan

1. Add focused payload and fallback tests before changing the component; implement the enrichment behind the existing payload construction path.
2. Add the structured card and disclosure while preserving the current response control; run the bounded backend/frontend checks and the focused Playwright spec.
3. Inspect the candidate diff and static references, remove the superseded monolithic rendering branch after parity, and rerun the focused checks.
4. Rollback is a normal candidate rollback: revert the code change while retaining persisted historical payloads and audit evidence. No database migration is required.

## Open Questions

The exact Spanish wording for each gate remains an implementation copy decision constrained by the Issue and the fields in the spec. Coverage of both `proposal_feasibility` and `apply_escalation` is explicitly pending validation during Apply/Verify; this design does not presume an additional human authorization.
