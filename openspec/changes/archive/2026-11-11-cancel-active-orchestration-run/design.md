## Context

The API currently admits and resumes a project's request through `POST /api/v1/projects/{project_id}/requests/run`; the CLI has `request run`, `request ack`, and `request complete`. `OrchestrationRunRepository` already owns durable Run state, and `WorktreeManager` already enforces durable ownership before cleanup. There is no supported cancellation route or CLI command. The current Run in Múltiplo is active, in `IMPLEMENTING/NEEDS_HUMAN`, has no `active_job_id`, and remains the project's active slot after its GitHub Issue was closed.

## Goals / Non-Goals

**Goals:**
- Give an authenticated operator one explicit, Run-targeted way to cancel a stopped human gate and free the active slot.
- Make the terminal transition auditable, race-safe, idempotent for the same request, and visible in the PWA and CLI.
- Preserve existing Run details and use repository and worktree lifecycle boundaries already present.

**Non-Goals:**
- Do not resume Apply, change attempt counters, create a new Run, or change OpenSpec behavior.
- Do not cancel an in-flight agent process. Reject cancellation while an active job/invocation exists; the action is available for a settled human gate.
- Do not change `request complete`, close a GitHub Issue, deploy, restart the scheduler, or write directly to PostgreSQL.

## Decisions

1. **Target the Run explicitly.** Add `POST /api/v1/projects/{project_id}/runs/{run_id}/cancel` with a reason and idempotency key. Validate project binding and re-read the Run under the repository transaction before changing it. An inactive/terminal Run or one with an active stage job returns a conflict without state changes. This also covers orphaned `ADMITTED` Runs with no job, the failure described by Issue #298.
2. **Keep cancellation separate from completion and gate resolution.** Add a small `RunCancellationService` using the Unit of Work and run repository. It records actor/reason/time alongside existing `stop_details`, sets `CANCELLED`, clears `human_gate`, and sets `is_active=false`; the update and durable event/action evidence commit together. Repeated requests with the same idempotency key return the recorded result; a different request against a terminal Run fails closed.
3. **Use the same service from CLI and API.** Add `minime request cancel <project_id> --run-id <id> --reason <text>`; do not overload `request complete` or its physical-validation meaning.
4. **Expose only an eligible gate action.** Add a cancel control beside the current human gate, render it only for an active `NEEDS_HUMAN` Run with no active job, and require an explicit confirmation. The UI sends the exact Run ID and an idempotency key and displays server rejection without optimistic terminal state.
5. **Honor workspace ownership checks.** After the durable terminal transition, call the existing `WorktreeManager` cleanup only with persisted ownership records bound to the Run. If ownership is ambiguous or the worktree is dirty/unobservable, preserve the workspace and ownership and report cleanup as unresolved; never delete by path guess or hide a partial cleanup result.

Alternatives rejected: changing `request complete` would conflate validation acceptance with cancellation; direct SQL would bypass the domain/repository and audit path; treating natural-language gate text as cancellation would be ambiguous; canceling active jobs without a process-termination contract could orphan agent work.

## Risks / Trade-offs

- Cancellation can release the project slot while a dirty candidate remains for safety. The UI and response must distinguish Run cancellation from workspace-cleanup completion.
- A request racing with stage dispatch must fail closed if the Run no longer matches the eligible gate or has acquired an active job.
- The first release supports settled human gates. Active-process cancellation remains unavailable until a separately specified lifecycle can terminate and verify the process safely.
