## Context

The backend already owns provider/model identity and discovery in `provider_model_registry`. Its catalog DTO currently has discovery status but no operator enablement, and `CanonicalProfileResolver` validates availability and role capabilities. Harness status is returned by the existing authenticated refresh endpoint. Project role assignments are persisted by `PATCH /api/v1/projects/{project_id}` in the four canonical profile keys. The Angular shell has routed feature views and an authenticated `ApiService`; no administration route currently exists.

The implementation must keep two separate facts: `discovery_status` describes observed discovery/diagnostic results, while `is_enabled` records the operator's decision to permit a model for role assignment and resolution.

## Goals / Non-Goals

**Goals:**
- Persist and expose operator enablement for every registry model without changing discovery evidence.
- Make enable/disable updates concurrency-safe and prevent disabled models from new assignments or resolution.
- Provide the Issue #253 Angular panel for harness state, model toggles, and three role assignments on a selected project.
- Show only API-confirmed toggle and assignment state.
- Keep the “Test Connection” control visible while deferring its behavior to Issue #254.

**Non-Goals:**
- Credential diagnostics, changes to the existing refresh implementation, or any `/test` operation owned by #254.
- Reworking the Projects view, project profile contract, fallback role, other views, or provider/model discovery semantics.
- Creating a second provider/model registry or a separate persisted role-assignment store.

## Decisions

### Store enablement as an independent registry field

Add non-null `is_enabled` to `provider_model_registry`, with a database and ORM default of `true`. The Alembic migration will follow the verified current head `f13_provider_model_registry`, add the column with a true server default so existing rows retain their prior availability, and advance `EXPECTED_ALEMBIC_HEAD` to the new revision. The model DTO and `catalog_payload` expose the field. Discovery upserts update discovery metadata and preserve `is_enabled`.

This uses the canonical registry as the single source of truth. Reusing `discovery_status` was rejected because discovery is observed evidence and must not be overwritten by an operator preference.

### Toggle through a version-checked admin operation

Add an authenticated `PATCH /api/v1/admin/providers/models/{model_id}/enabled` accepting the desired `is_enabled` value and current registry `version`. The repository updates only the operator state and version transactionally; stale versions return conflict, and the response contains the persisted model DTO. The catalog remains inclusive of disabled entries. `CanonicalProfileResolver` rejects disabled rows independently from discovery checks, so a disabled model cannot be assigned or resolved even if its discovery status is available.

The Angular client sends the currently displayed version and changes its displayed state only after the server response succeeds. A failed or stale update retains the last confirmed value and presents the API error.

### Keep harness status tied to real refresh results

The panel reads the existing admin catalog for models and harness identities. A visible refresh action invokes the existing `/api/v1/admin/providers/refresh` operation; cards show each returned harness status and summary, including unavailable results. The UI does not infer “installed” from a harness identifier or fabricate a status before a refresh result exists. It shows an unobserved/loading state until the endpoint returns.

### Add a dedicated administration route

Create a focused Angular feature and route, linked from the existing navigation shell. The view loads projects and lets the operator select one; it loads that project's current profiles and saves through the existing project update API. The visible role labels map to `thinking`, `execution`, and `independent_review`. The view does not alter `fallback` or use client-only persisted state. Provider/model options come from the live catalog and are filtered by enabled state and role capability; server validation remains authoritative.

Render “Test Connection” as a visible disabled control with an explanation that credential diagnostics are handled by #254. This avoids a dead control or an implied successful test while respecting the issue boundary.

### Verify against observable behavior

Focused backend coverage will prove migration defaults, independent field behavior, version conflict handling, refresh preservation, and resolver rejection. Angular coverage will exercise catalog/status rendering, server-backed toggle success/failure, project role mapping/save, and the deferred diagnostic control. The frontend build (`ng build` or `tsc --noEmit -p frontend/tsconfig.app.json`) is required evidence in addition to tests.

## Risks / Trade-offs

- Existing projects may reference a model later disabled by an operator. The profile remains stored, but subsequent validation/resolution rejects it; the UI must expose the failure and allow selection of an enabled alternative.
- Harness refresh performs the existing bounded CLI inspection and persists observed diagnostics. It remains an explicit operator action rather than an implicit side effect on page load.
- Marking legacy registry rows enabled preserves their previous eligibility; discovery status and freshness checks continue to govern whether they are actually assignable or resolvable.
- The Test Connection control is deliberately unavailable until #254 supplies its behavior.
