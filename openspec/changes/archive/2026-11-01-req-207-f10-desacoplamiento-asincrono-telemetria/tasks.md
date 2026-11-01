# Tasks

## 1. Asynchronous run dispatch and real-time event streaming

- [x] 1.1 Convert `POST /api/v1/projects/{project_id}/requests/run` and human clarification gates to immediate asynchronous response (`HTTP 202 Accepted`) with bounded background workers.
- [x] 1.2 Implement the lightweight in-memory `EventBroker` and FastAPI Server-Sent Events endpoint `GET /api/v1/events` (`text/event-stream`) to broadcast stage transitions, human gates, and quota updates instantly.
- [x] 1.3 Ensure background workers operate with fresh, bounded database sessions, preserving transactional isolation, idempotency, and fail-closed persistence.

## 2. Quota window telemetry and CLI strategy adapters

- [x] 2.1 Implement the `ProviderQuotaStrategy` pattern encapsulating Antigravity CLI (`agy --print="/usage"`), Codex, and DeepSeek balance queries.
- [x] 2.2 Parse five-hour rolling window usage, remaining percentages, and reset timestamps with an in-memory TTL cache of 60 seconds.
- [x] 2.3 Expose observed live telemetry via `/api/v1/providers/quotas` without returning hardcoded mock percentages or unverified assumptions.

## 3. PWA compact capacity cards and real-time reactive state

- [x] 3.1 Replace radial gauges with responsive, compact capacity cards featuring horizontal progress bars, status badges, and reset countdowns.
- [x] 3.2 Wire `RefreshService` in Angular to consume the backend SSE stream via native `EventSource`, updating view signals immediately upon event arrival with lazy fallback polling.
- [x] 3.3 Harmonize reactive run projections across Dashboard, Trabajo, Trabajo Actual, and Backlog so an active run is never duplicated as next work.
- [x] 3.4 Wire the manual refresh header action with a transient synchronization indicator and full snapshot revalidation.
- [x] 3.5 Fix light mode contrast and accessibility across the sidebar and capacity cards to ensure full WCAG AA compliance.

## 4. Run auto-recovery and autonomous continuation

- [x] 4.1 Implement startup discovery and fenced claim recovery for orphaned or interrupted runs without requiring manual operator intervention.
- [x] 4.2 Enforce autonomous stage transitions from implementation to test execution and code review, preserving human gates strictly for legitimate ambiguity or high complexity.
- [x] 4.3 Lock out and visually hide duplicate execution triggers for subsequent tickets while an active run is in flight.

## 5. Verification, regression testing, and evidence

- [x] 5.1 Execute unit and integration test suites covering HTTP 202 acceptance, SSE event broadcasting, quota parsing, and auto-recovery.
- [x] 5.2 Validate real E2E observable evidence for asynchronous run progress, instant human gate presentation, and live quota telemetry against an immutable candidate SHA.
- [x] 5.3 Run `openspec validate` and ensure the entire change specification is fully compliant with the governing canonical contracts.
