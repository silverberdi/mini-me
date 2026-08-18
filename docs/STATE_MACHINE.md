# State Machine

## Change states
`DISCOVERED → READY → IN_PROGRESS → NEEDS_HUMAN → APPROVED → MERGE_PENDING → CLOSING → DONE`

Exceptional/terminal paths: `BLOCKED`, `REJECTED`, `CANCELLED`.

`CHANGES_REQUESTED` is a human decision that returns the change to `IN_PROGRESS`; it need not be a long-lived portfolio state.

## Job stages
Typical path:

`QUEUED → PREPARING → IMPLEMENTING → CHECKING_IMPLEMENTATION → REVIEWING → [CORRECTING loop] → CHECKING_FINAL → AUDITING → [DEPLOYING_PREVIEW → VERIFYING_PREVIEW → AWAITING_HUMAN_VALIDATION when required] → AWAITING_HUMAN → FINALIZING → PUSHING/PR_READY → AWAITING_MERGE → DEPLOYING_PRODUCTION → VERIFYING_PRODUCTION → POST_MERGE_CLOSING → COMPLETED`

Temporary/error states include `RETRY_SCHEDULED`, `WAITING_CAPACITY`, `WAITING_DEPENDENCY`, `BLOCKED`, `FAILED`, `CANCELLED`.

## Scheduler modes
- `RUN`: may admit new READY changes.
- `DRAIN`: both primary subscription providers exhausted; do not admit new READY work; paid fallback may finish eligible in-flight work.
- `WAIT`: no eligible drain work; await primary capacity recovery.

Scheduler mode is not a change state.

## Transition invariants
- State changes occur through centralized domain transition functions.
- Current state update + event append occur atomically where practical.
- No `READY → DONE`, `IMPLEMENTING → APPROVED`, or similar bypasses.
- `FAILED` attempt does not automatically fail the change.
- `WAITING` means mini me knows the recovery condition and does not currently require human judgment.
- `BLOCKED` means safe progress requires human intervention or resolution.
