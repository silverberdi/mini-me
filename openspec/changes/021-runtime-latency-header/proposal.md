# Proposal: Add runtime diagnostic latency header to API health check

## Problem Statement
Include X-Runtime-Diagnostic header on API health check response to measure round-trip gateway latency.

## Proposed Change
Deliver the capabilities and requirements defined for `021-runtime-latency-header`.

## Acceptance Criteria
- GET /api/health includes X-Runtime-Diagnostic header in response
- Header contains timestamp in ISO format
- All deterministic checks pass

## Non-Goals
- Opportunistic refactoring outside the defined acceptance criteria.
- Undocumented scope changes or speculative features.

## Capabilities
- `add-runtime-diagnostic-latency-header-to-api-health-check`: Add runtime diagnostic latency header to API health check
