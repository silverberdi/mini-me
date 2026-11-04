## MODIFIED Requirements

### Requirement: Credential and harness diagnostic
The system SHALL provide authenticated, non-secret diagnostic facts for configured model-provider credentials and harness availability, including permission, command-version, and last-observed facts where the configured provider exposes them. It SHALL expose `POST /api/v1/admin/providers/{provider}/test` for provider IDs represented in the administrative model catalog and configured at runtime. The endpoint SHALL use only an explicitly supported bounded check that does not invoke model inference or materially consume provider budget; it SHALL report an unavailable status when no such check exists. A diagnostic response SHALL include a status, latency in milliseconds when a check ran, and sanitized detail. A failed or unobservable diagnostic SHALL NOT authorize execution. Diagnostics SHALL NOT persist or return secret values, authorization headers, raw provider response bodies, or unsanitized exception text.

#### Scenario: Valid credential diagnostic
- **WHEN** an authenticated operator tests a configured catalog provider and its supported non-inference authentication check succeeds
- **THEN** the response reports success, the measured latency, and non-secret diagnostic detail for that provider

#### Scenario: Invalid credential diagnostic
- **WHEN** an authenticated operator tests a configured catalog provider and the provider rejects its credential
- **THEN** the response reports failure with sanitized actionable detail, does not expose credential material, and does not authorize execution

#### Scenario: Unsupported inexpensive check
- **WHEN** an authenticated operator tests a configured catalog provider for which no bounded non-inference check is supported
- **THEN** the response reports unavailable without attempting an inference or another costly operation

#### Scenario: Reject an unconfigured provider
- **WHEN** an authenticated operator tests a provider ID that is absent from the model catalog or runtime configuration
- **THEN** the endpoint rejects the request without dispatching a provider operation

#### Scenario: Require an authenticated operator
- **WHEN** a request to test a provider has no valid authorized operator session
- **THEN** the endpoint rejects the request and performs no diagnostic

#### Scenario: Sanitize provider failure data
- **WHEN** a provider response or exception contains a token, key, credential, authorization header, or raw body
- **THEN** the diagnostic response contains only a bounded sanitized status/detail and latency, with no secret-bearing source text
