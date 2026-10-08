## Context

See proposal.md for motivation. `ControlPlaneService._execute_cancel` currently changes and saves
the run, then commits its action record, but does not converge `run.active_job_id`. The existing
Postgres job repository already owns valid status transitions and its normal transitions join the
caller session transaction.

## Goals / Non-Goals

**Goals:**

- Treat run cancellation and linked-job terminalization as one UoW command.
- Fail before run mutation when a declared linked job is missing.
- Provide a narrow repeat-safe reconciliation for the historical cancelled-run/active-job shape.

**Non-Goals:**

- Changing scheduler selection rules, generic job mutation APIs, Change/Backlog lifecycle,
  recovery policy, or cleanup behavior.

## Decisions

1. **Use `JobRepositoryInterface.transition` for non-terminal linked jobs.** The repository
   validates the Job state graph, emits its existing transition evidence, and preserves the single
   authority for Job status. Direct assignment is prohibited.

2. **Resolve and validate linkage before mutating the run.** A missing `active_job_id` target is an
   inconsistent identity, so cancellation raises a clear control-plane error rather than claiming
   success. A null link remains valid and permits normal run-only cancellation.

3. **Commit successful job and run updates once.** Both repository writes use the request UoW and
   the existing cancellation commit remains the sole success commit. If any mutation fails,
   `execute_action` must rollback before recording a FAILED action record in a clean transaction;
   this prevents the exception handler from committing dirty partial state.

4. **Put historical repair on the existing control-plane reconciliation boundary.** Add a narrow
   idempotent method that accepts only an already-cancelled inactive run and converges its declared
   non-terminal linked job. It performs no run mutation or side-effect replay, avoiding a generic
   arbitrary-job action endpoint.

## Risks / Trade-offs

- [A cancelled run can point to a missing job] → reject without state mutation and persist a
  failed audit record.
- [A Job transition throws after in-memory writes] → rollback before the failure audit transaction.
- [Historical repair is called repeatedly] → terminal linked jobs are preserved without transition.

## Migration Plan

No schema migration is required. Deploy the code, then invoke the new narrow reconciliation through
its canonical authority for historical cancelled runs only after operational approval. Rollback is
the standard code rollback; no data is deleted or rewritten by deployment.
