## Purpose

Provides durable network transport resilience with exponential backoff, jitter, and Retry-After adherence for external provider API interactions, coupled with supervisory session independence ensuring orchestration operations survive operator terminal disconnects without data loss or duplicate actions.

## ADDED Requirements

### Requirement: Transport-level HTTP/SSE retries with exponential backoff and jitter
The system SHALL wrap external LLM and review provider HTTP/SSE client calls in a resilient transport layer that automatically retries transient network interruptions (socket connection resets, TCP read timeouts, DNS temporary failures, HTTP 429, 502, 503, 504) using exponential backoff with random jitter and strict adherence to provider `Retry-After` headers.

#### Scenario: Transient socket connection reset is recovered automatically
- **GIVEN** an active HTTP or SSE stream call to a provider (e.g. DeepSeek Direct or Google Cloud Code PA)
- **WHEN** a transient socket drop occurs (`ConnectionResetError`, `read: connection reset by peer`) before receipt of an authoritative terminal response
- **THEN** the system executes up to 4 automatic retries with exponential backoff (e.g., 1s, 2s, 4s, 8s plus jitter)
- **AND** the operation resumes transparently without halting the orchestration engine or requiring human operator intervention.

#### Scenario: Non-retriable permanent errors fail fast
- **GIVEN** an external provider API invocation
- **WHEN** the provider responds with a permanent client error (HTTP 400 Bad Request, 401 Unauthorized, 403 Forbidden, invalid JSON response structure, or budget limit exceeded)
- **THEN** the transport layer SHALL NOT retry
- **AND** the error is classified immediately as a deterministic failure, persisting appropriate diagnostic and ledger records.

### Requirement: Preservation of uncertain post-send outcomes and idempotency
The system SHALL classify external operations as either pre-send failures (safe to re-dispatch) or post-send uncertain outcomes. When an external request has been transmitted and may have been consumed by the provider, the system SHALL NOT blind-retry the call. Instead, the system SHALL preserve the transaction with status `UNKNOWN` or `AMBIGUOUS`, record the unresolved financial exposure, and reconcile durable state before any subsequent dispatch.

#### Scenario: Uncertain inference outcome preserves ledger and avoids duplicate spend
- **GIVEN** a paid review or completion request transmitted to an external provider
- **WHEN** the transport drops after transmission without an explicit verdict or receipt
- **THEN** the system retains the existing reservation as unresolved exposure
- **AND** the system SHALL NOT dispatch an identical paid request without prior observation or explicit operator reconciliation.

### Requirement: Daemon orchestration independence from supervisory sessions
The system SHALL execute background orchestration runs, jobs, and sandbox child processes independently from the interactive terminal or session lifecycle of Codex, Antigravity, or user CLI clients. Supervisory session disconnection SHALL NOT abort active runs, drop durable worktrees, or corrupt checkpoint fencing.

#### Scenario: Supervisory session disconnects while job is running
- **GIVEN** a job actively executing inside the sandbox or awaiting external review
- **WHEN** the client terminal or supervisory AI session disconnects unexpectedly
- **THEN** the daemon continues executing the job to its configured checkpoint
- **AND** upon reconnection of a supervisor or operator CLI, the runtime reports the current durable state without duplicating actions or restarting finished stages.
