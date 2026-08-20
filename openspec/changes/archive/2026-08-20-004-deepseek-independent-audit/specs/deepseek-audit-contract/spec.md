## Purpose

Defines the direct API execution contract for DeepSeek Direct independent audit, ensuring direct API communication with credential isolation, zero OpenRouter routing, rich contextual prompt generation, single-payload fail-closed response parsing, and strict schema validation.

## ADDED Requirements

### Requirement: Direct DeepSeek API invocation
The system SHALL invoke DeepSeek Direct via direct HTTP API calls using `DEEPSEEK_API_KEY` retrieved from secure host configuration and SHALL NOT route, proxy, or substitute audit requests through OpenRouter or any fallback provider.

#### Scenario: Audit executed via direct DeepSeek endpoint
- **WHEN** an audit execution is triggered for an eligible candidate that passed complementary review
- **THEN** the system makes a direct API call to the configured direct DeepSeek API endpoint using `DEEPSEEK_API_KEY` without passing through intermediate proxy providers, fallback providers, or alternate model substitutions.

#### Scenario: OpenRouter proxying or provider substitution strictly rejected
- **WHEN** an audit execution is configured or invoked
- **THEN** the system verifies that the target provider endpoint is direct DeepSeek; any configuration attempting to route `DEEPSEEK_API_KEY` through OpenRouter or substitute alternative providers is rejected immediately before making network calls.

### Requirement: Structured audit prompt context
The system SHALL construct a standardized, read-only audit context including the change proposal, active delta specifications, candidate Git diff against base SHA, deterministic check run outcomes, and the complementary review verdict (`READY_TO_MERGE`) with all structured findings.

#### Scenario: Complete audit prompt constructed
- **WHEN** preparing the auditor payload for an execution job
- **THEN** the system compiles the full candidate diff against `base_sha`, relevant OpenSpec specifications/tasks, prior check execution summaries, and prior review findings into the auditor prompt context.

### Requirement: Fail-closed structured audit response validation
The system SHALL parse DeepSeek auditor responses expecting exactly one authoritative structured JSON payload conforming strictly to `schemas/audit-result.schema.json`, and SHALL fail closed on missing, malformed, multiple, ambiguous, or unsupported outputs.

#### Scenario: Single valid audit response conforming to schema accepted
- **WHEN** DeepSeek Direct returns a response containing exactly one valid JSON payload (optionally enclosed in a single markdown code fence) matching `schemas/audit-result.schema.json`
- **THEN** the system parses the JSON output, validates `risk` (`low`, `medium`, `high`, `critical`), `summary`, and structured `findings` (`severity`, `category`, `message`, `file`, `location`), and records the audit outcome.

#### Scenario: Multiple or ambiguous JSON payloads fail closed
- **WHEN** DeepSeek Direct returns output containing multiple JSON objects, conflicting payloads, or embedded JSON fragments within explanatory prose
- **THEN** the system rejects the output without attempting heuristic or permissive extraction, emits a `MALFORMED_AUDIT_OUTPUT` event, and marks the audit status as `AUDIT_FAILED`.

#### Scenario: Schema violation or unsupported risk/severity values fail closed
- **WHEN** DeepSeek Direct returns invalid JSON, unrecognized fields (`additionalProperties`), or unsupported risk/severity enum values
- **THEN** the system marks the audit attempt as `AUDIT_FAILED` with a schema validation error reason, logs a structured error event, and leaves the candidate blocked.

### Requirement: Auditor error handling and timeouts
The system SHALL enforce bounded execution timeouts and handle network failures, authentication errors, or rate limits during auditor invocation.

#### Scenario: Auditor timeout handled safely
- **WHEN** a DeepSeek Direct API request exceeds the configured timeout threshold
- **THEN** the system cancels the in-flight request, marks the audit status as `AUDIT_TIMED_OUT`, and records an `AUDIT_TIMEOUT` event.

#### Scenario: Provider API error recorded
- **WHEN** the DeepSeek API returns an HTTP 4xx or 5xx error (e.g. invalid API key, quota limit, or server outage)
- **THEN** the system marks the audit status as `AUDIT_FAILED` with provider error details recorded in PostgreSQL logs with secret redaction.

### Requirement: Secret isolation and redaction
The system SHALL keep `DEEPSEEK_API_KEY` strictly isolated in memory and SHALL redact the secret from all persisted prompt logs, job logs, audit records, events, and API/CLI observability responses.

#### Scenario: Audit logs pass through secret redaction
- **WHEN** audit prompts, responses, or error traces are recorded or streamed
- **THEN** any occurrence of API keys or sensitive host secrets is replaced with redaction placeholders before database persistence or client serialization.
