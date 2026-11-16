## 1. Apply capacity preflight

- [x] 1.1 In normal `SchedulerMode.RUN`, allow the configured primary to dispatch Apply when its persisted `provider_health.status` is `AVAILABLE` and no active failure or exhaustion is recorded, without gating on the age of `last_success_at`.
- [x] 1.2 Restrict the strict `last_success_at <= 60s` condition to the existing `SchedulerMode.DRAIN` peer-outage recovery path; preserve current fallback and budget authorization.
- [x] 1.3 Add focused tests for an old `last_success_at` with an otherwise healthy `AVAILABLE` record in `RUN`, active failure/exhaustion blocking dispatch, and the 60-second condition applying only in `DRAIN` peer-outage recovery.

## 2. Durable pre-process failure recovery

- [x] 2.1 Classify known failures occurring before workflow process creation and close the existing stage invocation with a terminal PostgreSQL event and released/fenced claim.
- [x] 2.2 Allow at most one automatic retry only when the failed preflight is proven, the prior coordinator ended, and the same candidate/worktree fingerprint is unchanged; keep ambiguous or changed-candidate cases fail-closed.
- [x] 2.3 Add regression tests proving a preflight failure does not leave an orphaned `STARTED` invocation, repeated failures do not loop indefinitely, and live/unobservable process or changed-worktree evidence still blocks recovery.

## 3. End-to-end evidence

- [x] 3.1 Run a PostgreSQL-backed integration/E2E that exercises the coordinator's Apply dispatch and preflight failure recovery, then verifies the actual process invocation outcome and linked durable stage events for the same Run, stage, and candidate.
- [x] 3.2 Run the relevant regression suites and native OpenSpec Verify; record results against the exact candidate SHA and do not count simulated process/provider outcomes as real E2E evidence.
