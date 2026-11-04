## Why

The live provider/model registry and project role APIs are available, but operators cannot manage them from the Angular control center. The model catalog also lacks an operator-controlled enabled state, so the requested model toggle cannot be persisted safely by a UI alone.

## What Changes

- Add an independent operator-enabled state to each provider-model registry entry, expose it in the catalog, and provide a version-checked operation to change it without altering discovery diagnostics.
- Prevent disabled models from being assigned or resolved for execution while retaining their catalog and discovery information.
- Add an Angular administration view showing harness diagnostics, model state with a persisted toggle, and provider/model selectors for thinker, implementer, and reviewer on the selected project.
- Render the “Test Connection” control as a non-operational handoff placeholder; credential testing remains the separate Issue #254.

## Capabilities

### New Capabilities
- `provider-model-administration-ui`: Operator-facing Angular administration for harness status, persisted model enablement, and selected-project role assignments.

### Modified Capabilities
- `provider-model-registry`: Add durable operator enablement separate from read-only discovery status, including API and assignment enforcement.

## Impact

- Backend: provider-model registry DTO/repository/resolver, authenticated admin API, SQLAlchemy model, Alembic migration chained after `f13_provider_model_registry`, and `EXPECTED_ALEMBIC_HEAD`.
- Frontend: a new Angular administration feature and route/navigation entry, using the existing authenticated API client and project/catalog endpoints.
- Verification: focused backend and Angular coverage, migration upgrade/downgrade coverage where available, and `ng build` or `tsc --noEmit` evidence. No credential diagnostic endpoint or behavior is added.
