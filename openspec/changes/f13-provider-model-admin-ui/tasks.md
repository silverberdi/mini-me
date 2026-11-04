## 1. Durable operator model state

- [x] 1.1 Add non-null `is_enabled` to the provider-model ORM and a conservative Alembic migration after `f13_provider_model_registry`, defaulting existing and newly inserted rows to enabled; update `EXPECTED_ALEMBIC_HEAD` to the new revision.
- [x] 1.2 Extend registry DTO/catalog serialization and add an authenticated version-checked enablement operation that changes only `is_enabled` and the row version; preserve the operator state during discovery upserts.
- [x] 1.3 Reject disabled entries in canonical role validation/resolution independently of `discovery_status`, with errors that distinguish operator-disabled state from discovery diagnostics.
- [x] 1.4 Add focused backend tests for migration/default behavior, catalog serialization, enable/disable persistence, stale-version conflict, refresh preservation, and rejection of disabled role models.

## 2. Angular provider/model administration

- [x] 2.1 Add a routed administration feature and navigation entry that loads the existing admin catalog and displays provider/model metadata with discovery and operator-enabled states shown separately.
- [x] 2.2 Add an explicit harness refresh action using the existing refresh endpoint and render each returned harness status/summary; show an unobserved state before a real response and preserve per-harness failures.
- [x] 2.3 Implement model toggles using the version-checked backend operation; update the UI only from a successful response, and retain the last confirmed state with an error on failure/conflict.
- [x] 2.4 Load projects and let the operator select one; map thinker/implementer/reviewer to `thinking`/`execution`/`independent_review`, load current profiles, and save provider/model selections through the existing project update API without changing `fallback`.
- [x] 2.5 Render the “Test Connection” control as unavailable with a clear handoff to Issue #254 and make no credential-test request.
- [x] 2.6 Add focused frontend tests for harness and model state rendering, server-confirmed toggle success/failure, role mapping/save behavior, and the non-operational credential-test control.

## 3. Integration and validation

- [x] 3.1 Add an integration test against the real application API and persistent test database that toggles a model, reloads the catalog, and verifies the persisted state and unchanged discovery evidence; also verify that a saved project role selection is returned by the project API and disabled models are rejected.
- [x] 3.2 Verify the Angular production build with `npm run build` (or `npx tsc --noEmit -p frontend/tsconfig.app.json`) and run the focused backend/frontend tests for this change.
- [x] 3.3 Run migration upgrade/downgrade validation, `openspec validate f13-provider-model-admin-ui --strict`, and `git diff --check`; record observable command results before marking tasks complete.
- [x] 3.4 Update the stale source-matching assertion in `frontend/tests/human-gate-current-payload.test.mjs` to match `run.stop_details?.['human_payload']`, leaving the other assertions and component unchanged; verify the complete frontend suite reports 18/18 passing.
