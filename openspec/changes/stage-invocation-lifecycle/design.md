## Context

See `proposal.md` for motivation. The coordinator already has append-only `orchestration_stage_events`, fenced PostgreSQL `recovery_claims`, and durable `operator_action_records`. Transition events do not currently form a uniform invocation history, and native Verify dispatch is not protected by the same durable dispatch path used by Explore/Propose. The active human response endpoint currently schedules work through a process-local idempotency map.

## Goals / Non-Goals

**Goals:**
- Reuse existing durable records to capture invocation lifecycle and enforce one active dispatch per run/stage/candidate.
- Extend the protection to all coordinator stage workflow dispatches, including Verify.
- Make gate acceptance durable and idempotent while preserving the current API response path and operator decision semantics.
- Recover one expired invocation only when ownership and candidate identity are verifiably safe.

**Non-Goals:**
- Create a new UI, stage-history endpoint, workflow implementation, or OpenSpec substitute.
- Change what native OpenSpec workflows do or how their results are interpreted.
- Automatically resolve a human gate or retry an ambiguous/second worker interruption.

## Decisions

### Append invocation lifecycle events to the existing stage-event journal

Use `orchestration_stage_events` with invocation-specific `event_type` values for start, completion, human-required, failure, and abandonment. Each event carries `attempt_id`, candidate identity, the observed native execution result/handoff, and timestamps in `evidence_references`; the terminal event records elapsed duration. Preserve native question/options exactly when supplied. The journal remains append-only. A candidate SHA is captured when available; before that, the attempt binds to the run's managed worktree/branch identity and generation, then records the observed SHA without changing the attempt identity. The coordinator records evidence and dispatch boundaries; it does not inspect or synthesize OpenSpec artifacts or infer a native workflow outcome.

**Alternative considered:** add a dedicated stage-attempt table. Rejected because the existing event journal already stores append-only run/stage evidence, while a separately claimed `recovery_claims` row supplies the active exclusion. A new table would duplicate lifecycle state without adding a required query or behavior.

### Claim per run, stage, and candidate using the existing fenced lease repository

Before any stage workflow dispatch, acquire a durable claim whose key includes run ID, stage, and a stable candidate-identity fingerprint. Commit the start event and claim before external invocation. Renew the lease while the process is active. A stale worker must fail fencing checks before it can append a terminal event or advance orchestration. Release only after a terminal invocation event is committed. Existing run-wide claim users keep their current keys.

**Alternative considered:** use only a process-local lock or `_accepted_operations`. Rejected because it does not serialize independent workers and does not survive a process restart.

### Persist gate acceptance through existing operator-action records

When accepting a response, lock and validate the active run/gate, then persist a `RESOLVE_GATE` action before scheduling the worker. Derive its request identity from the run, current gate fingerprint, and response fingerprint; store the accepted response needed for continuation with that action. Repeating the same response for the same gate returns the existing accepted operation and cannot schedule another dispatch, including after restart or completion. Pass the accepted response as context to the same native stage workflow (including Apply or Verify when that stage owns the gate); preserve the workflow's returned handoff without replacing its behavior. A later gate has a different fingerprint and remains independently answerable. The current PWA interaction remains unchanged.

**Alternative considered:** rely on the in-memory operation map or only deduplicate active stage claims. Rejected because both permit a repeated submission to dispatch again after a worker finishes or after process restart.

### Bound crash recovery to one safe re-dispatch

The durable start event records the coordinator process identity (PID, host identity, boot identity, and OS process-start marker). `AgentProcessConfinement` reports the spawned process-group identity immediately after creation through a callback; the coordinator appends that evidence to the same attempt before the workflow proceeds. If a process-start record cannot be persisted, terminate the confined process and fail the dispatch closed. On Linux, read the process-start marker from `/proc/<pid>/stat` and pair it with `/proc/sys/kernel/random/boot_id`; on macOS, use the operating-system process start timestamp and boot identity. The process group is the session leader PID created by `start_new_session=True`. If a platform cannot provide a stable identity, allow the original workflow only with durable `recovery_proof=UNAVAILABLE`; never auto-recover that attempt.

When a lease expires without a terminal event, recovery first observes process state before taking over the claim. It proves the recorded coordinator PID/start marker is gone or belongs to a different process, then proves the recorded process group no longer exists, and only then acquires the higher fencing generation. A live coordinator process, present process group, missing process evidence, different host/boot context, or unsupported platform is ambiguous and stops for operator intervention. Only when both processes are confirmed gone and the same run, stage, worktree/branch, generation, and candidate SHA still match may recovery record the abandoned attempt and make one re-invocation through the existing native workflow. Do not inspect OpenSpec artifacts or implement a parallel decision about workflow progress. A second interruption stops for the operator. Human-required attempts are terminal attempts, not crashed attempts, and wait for accepted operator response instead.

**Alternative considered:** retry on every lease expiry. Rejected because repeated worker loss could recreate the Verify loop and consume resources indefinitely. Immediate terminal failure on the first expiry was also rejected because it would discard the bounded recovery requested by the Issue.

## Risks / Trade-offs

- [Risk] The generic event journal may contain older consumers that assume every event is a stage transition → update consumers to filter for transition event types; add a regression test proving invocation records do not appear as transitions.
- [Risk] A delayed worker may still finish after lease expiry → fencing must be checked before terminal persistence and stage advancement; a lost fence cancels or discards the stale result.
- [Risk] Human responses may contain sensitive operator context → store only the response needed for the accepted continuation, redact secrets using existing sanitization, and do not duplicate it in event evidence.
- [Risk] A lease may expire while the old coordinator or workflow process is still alive → persist coordinator and process-group identity and prove both are gone before re-invocation; unsupported platforms or missing evidence stop for operator intervention. Re-entry always uses the existing native workflow and never reconstructs its internal state.

- [Risk] A crash occurs after subprocess creation but before its identity is durable → terminate the process if the callback cannot persist; if the coordinator itself crashes in this interval, recovery sees missing process evidence and fails closed rather than guessing.

## Migration Plan

No new table is planned. Reuse the existing event, claim, and operator-action schemas. If implementation evidence shows an existing field cannot represent the required lifecycle without overloading incompatible semantics, stop and revise this design before adding a migration. Deploy code that reads legacy transition events unchanged and emits the new invocation event types only for new attempts.

## Safe Retirement Inventory

- **Replaced behavior:** unguarded or run-wide-only dispatches that do not record a uniform stage invocation lifecycle.
- **Old entrypoints/writers:** direct stage dispatch call sites in `NativeOrchestrationCoordinator`; the process-local `_accepted_operations` map currently protects in-flight request scheduling but is not durable gate-response authority.
- **Reachability/consumers:** coordinator stage branches and `POST /api/v1/projects/{project_id}/requests/run`; dashboard timeline currently projects stage-event rows and must distinguish transitions from invocation evidence. `_accepted_operations` remains for ordinary in-flight request scheduling.
- **Migration / historical owners:** retain all existing `orchestration_stage_events`, run checkpoints, recovery claims, external-action attempts, and operator-action records; no historical rows are deleted or rewritten.
- **New authority:** append-only invocation evidence plus per-stage/candidate fenced claims; durable gate-response action identity governs duplicate gate acceptance. OpenSpec remains the sole authority for native workflow behavior and result.
- **Actions:** MIGRATE stage dispatch entrypoints to invocation tracking; update timeline projection to retain only transition records as transitions; RETAIN `_accepted_operations` for ordinary in-flight request scheduling, existing stage-transition events, and human-gate semantics; REMOVE no database objects or historical records.
- **Evidence:** verify with call-site search, focused coordinator tests, PostgreSQL concurrency/recovery integration, process-group liveness cases (alive, absent, reused PID, missing identity, unsupported platform), and the exact candidate SHA.
- **Final state:** one guarded dispatch path per covered stage, without a second workflow engine or replacement of OpenSpec-native commands.

## Open Questions

None.
