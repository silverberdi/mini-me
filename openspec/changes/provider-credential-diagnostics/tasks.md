## 1. Backend provider diagnostic

- [x] 1.1 Add a structured diagnostic result contract separate from provider-health `probe_availability`, and implement bounded non-inference `GET /models` diagnostics for configured DeepSeek and OpenRouter adapters.
- [x] 1.2 Add authenticated `POST /api/v1/admin/providers/{provider}/test`, requiring provider membership in the admin catalog and runtime configuration; return finite status, latency, code, and sanitized detail without persisting diagnostic state.
- [x] 1.3 Add focused API/adapter tests for success, rejected credentials, timeout/transport error, unsupported check, unknown or unconfigured provider, unauthenticated access, and secret-bearing provider error/body data.

## 2. Administration UI connection test

- [x] 2.1 Enable the existing “Test Connection” control to call the provider diagnostic endpoint and render the server-confirmed status, latency, and safe detail without changing catalog state or inventing success.
- [x] 2.2 Add focused frontend coverage for provider selection, successful and failed results, unavailable status, and request failure; run the Angular production build or `tsc --noEmit` successfully.

## 3. Integrated diagnostic evidence

- [x] 3.1 Add an authenticated API integration E2E using a local HTTP provider fixture that observes the exact bounded non-inference request, verifies the returned result and secret sanitization, and confirms the provider registry/discovery state remains unchanged.
