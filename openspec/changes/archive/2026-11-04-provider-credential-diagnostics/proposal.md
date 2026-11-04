## Why

The administration panel delivered by Issue #253 renders “Test Connection” as a disabled handoff, so an operator cannot observe whether a configured model provider can authenticate. A bounded, non-inference diagnostic gives the operator a useful result without sending a model prompt or exposing credentials.

## What Changes

- Add authenticated `POST /api/v1/admin/providers/{provider}/test` for model providers represented in the administrative provider-model catalog and configured in the runtime.
- Return a status, measured latency, and sanitized diagnostic detail. Use only an explicitly supported, bounded, non-inference check; report unavailable when no safe check exists.
- Connect the existing “Test Connection” control to the endpoint and render the server-returned result.
- Never return credentials, tokens, authorization headers, raw provider response bodies, or unsanitized exception text.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `provider-model-registry`: define the authenticated, bounded, non-secret provider diagnostic endpoint and its failure behavior.
- `provider-model-administration-ui`: replace the disabled Issue #254 handoff with a server-backed connection test and visible result.

## Impact

- Backend: `src/minime/api/app.py` and the existing provider adapter diagnostic contract in `src/minime/adapters/provider_adapter.py`.
- Frontend: `frontend/src/app/features/admin-models/admin-models.component.ts` and focused frontend tests.
- Tests: provider adapter/API security and boundedness tests, plus frontend interaction coverage.
- Configuration review: current model registry entries and runtime provider configuration determine accepted provider IDs. GitHub App credentials and Google OAuth are configured in separate integration/authentication sections, not as model-provider entries in the admin model catalog; OpenAI is absent from the current runtime configuration. The existing button is attached to catalog model rows, so this Change does not add separate GitHub App or Google controls or invent an OpenAI provider.
