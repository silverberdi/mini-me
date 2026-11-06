## 1. Backlog state and actions

- [x] 1.1 Project the existing eligible Requests together with disabled Requests from `all_requests`, deduplicated by issue number while preserving eligible FIFO order; keep unrelated Request statuses out of the actionable list.
- [x] 1.2 Correct Backlog state labels and action visibility to use the authoritative `DISABLED` status; render an available reason only when the existing payload supplies it.
- [x] 1.3 Reuse the existing deactivate/reactivate endpoints and refresh authoritative Backlog data after success; preserve existing error behavior and never show success for a rejected or failed mutation.

## 2. Verification

- [x] 2.1 Add focused frontend tests for active/disabled projection, state and reason display, correct action/endpoint selection, refreshed state after success, and rejection without false success.
- [ ] 2.2 Exercise the real authenticated Backlog-to-existing-endpoint flow against a disposable GitHub-backed project; observe the remote disabled label, refreshed UI state, and FIFO exclusion, then reactivate and observe the label removal and existing FIFO eligibility rules. Record the exact run and external effects; do not use a mock as E2E evidence.

> Deferred follow-up: task 2.2 was not executed and remains incomplete. PR #279 explicitly deferred the real authenticated GitHub-backed E2E; PR #280 archived the Change without supplying that evidence. Keep this task unchecked until the label, refreshed UI state, FIFO exclusion and reactivation are observed in that E2E. See the [Issue #268 archive audit](../../../../docs/evidence/issue-268_archive-validation-audit_2026-11-04.md).
