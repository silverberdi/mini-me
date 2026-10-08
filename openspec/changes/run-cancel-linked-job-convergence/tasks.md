## 1. Cancellation Convergence

- [x] 1.1 Extend canonical CANCEL to validate the linked job, transition non-terminal linked jobs through the Job repository, and preserve terminal jobs.
- [x] 1.2 Make the CANCEL failure path roll back partial run/job mutations before persisting its failed action record.

## 2. Historical Reconciliation

- [x] 2.1 Add a narrow idempotent canonical reconciliation for an already-cancelled run with a non-terminal linked job.

## 3. Focused Evidence

- [x] 3.1 Add focused control-plane coverage for linked queued/running jobs, terminal jobs, missing linkage, transition failure rollback, active-selector release, preservation, and reconciliation idempotency.
- [x] 3.2 Run focused tests, strict OpenSpec validation, Ruff, formatting check, and diff check.
