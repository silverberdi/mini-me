## Context

See `proposal.md` for motivation and the provider-configuration boundary established from the current code. The registry-backed admin catalog is built from `provider_model_registry`; its seeded provider IDs are DeepSeek and OpenRouter. Runtime configuration also has CLI providers, a separate GitHub App integration, and Google operator-auth configuration. OpenAI is not configured. The existing admin control is attached to catalog model rows, so this Change diagnoses only a provider ID present in both the catalog and runtime provider configuration; it does not create integration controls for GitHub App or Google.

The DeepSeek and OpenRouter adapters already issue non-inference `GET /models` requests for availability, but return only a boolean and suppress diagnostic detail. The admin catalog and adjacent endpoints already require `AuthenticatedOperatorDep`.

## Goals / Non-Goals

**Goals:**

- Reuse the existing provider adapter and authenticated admin API boundaries.
- Preserve a structured, sanitized result for the operator without persisting a credential check as model discovery state.
- Make latency, unsupported checks, provider rejection, timeout, and transport failure distinguishable without forwarding provider-controlled text.

**Non-Goals:**

- Testing GitHub App authorization, Google OAuth client credentials, CLI harnesses, or providers absent from the model catalog.
- Checking model inference, making quota-consuming calls, changing provider/model assignments, or changing the registry schema.

## Decisions

1. **Use a structured, non-inference diagnostic on provider adapters.** Add a small diagnostic result contract separate from `probe_availability()`, whose boolean behavior is used by provider-health recovery. Implement the safe check for catalog-backed DeepSeek and OpenRouter using their configured base URL and credential for `GET /models`; use a short fixed timeout and report unavailable for any configured catalog provider without an explicit safe implementation. Do not dispatch a CLI prompt or model request. An alternative was to reuse `probe_availability()` directly, but it loses the distinction between auth rejection, timeout, and unsupported checks.

2. **Keep provider selection bound to the real catalog and runtime configuration.** Resolve the route parameter against provider IDs in the current registry catalog and require a matching runtime provider entry before invoking an adapter. Unknown or unconfigured IDs are rejected without provider I/O. Do not use a generic caller-supplied URL, accept credentials in the request, or synthesize support for OpenAI, Google, or GitHub App as model providers.

3. **Return finite diagnostic codes and safe messages.** The adapter maps known outcomes to fixed status/code/detail values such as success, credential rejected, timed out, unreachable, or unsupported. It measures elapsed milliseconds around the bounded operation. It does not include exception text, HTTP body, response headers, credential environment variable values, or auth headers. The endpoint returns the diagnostic outcome as data; it does not turn provider failures into application exceptions that could leak transport details.

4. **Keep diagnostics transient.** The POST operation does not update `provider_model_registry`, discovery status, model enablement, or provider-health recovery state. The UI holds the latest result in component memory, keyed by provider ID. Persisting a connection result was rejected because the issue asks for an on-demand response and a stale persisted result could be mistaken for current credential validity.

5. **Wire the existing catalog control directly.** The Angular control sends the provider ID from its catalog row and renders the response status, latency when measured, and safe detail. A failed HTTP request remains a UI error; it cannot synthesize a success result or alter catalog state.

## Risks / Trade-offs

- [A successful `GET /models` proves that the provider accepted the configured credential and served a lightweight catalog response, not that a model has available inference quota] → Label the result as a connection/authentication check and do not claim inference capacity or authorize execution.
- [Provider APIs can return secret-bearing or account-specific response bodies] → Discard provider body/header text from the result and expose only fixed diagnostic codes and messages.
- [Runtime configuration can contain additional provider IDs later] → Keep unsupported providers fail-closed as unavailable until a bounded diagnostic implementation is explicitly added; do not infer a check from a provider name.
- [A provider test can be repeated by an operator] → Bound every request with a short timeout and keep it read-only and non-inference; no new retry loop or background job is introduced.

## Migration Plan

No database or configuration migration is required. Deploy the additive API route and adapter result contract, then enable the existing UI control. Rollback consists of reverting the application change; no persisted diagnostic data requires cleanup.
