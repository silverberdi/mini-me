## Context

See `proposal.md` and Issue #404. At base `d7ae979c`, `CapacityLifecycleService.can_execute_inflight_apply()` requires a successful primary result in the previous 60 seconds, and `CliAgentRunner.check_capacity_preflight()` applies that predicate to every Apply before considering the configured fallback. That predicate was designed for in-flight execution during a peer outage; applying it during normal `SchedulerMode.RUN` rejects an otherwise eligible persisted primary merely because the system was idle.

The coordinator records `STAGE_INVOCATION_STARTED` before invoking Apply. If the runner raises during preflight, the Apply handler returns `PAUSED` from its exception branch without calling `_finish_stage_invocation()`. This leaves an incomplete event and claim that later recovery treats as ambiguous. Existing stage events, candidate fingerprints, claims, and terminal outcomes are the persistence boundary; this Change should not add another state store.

## Goals / Non-Goals

**Goals:**
- In normal `SchedulerMode.RUN`, dispatch Apply through the configured primary when its persisted `provider_health` status is `AVAILABLE` and no active failure or exhaustion is recorded, regardless of how old `last_success_at` is.
- Apply the strict `last_success_at <= 60s` condition only to the existing in-flight peer-outage recovery path in `SchedulerMode.DRAIN`.
- Preserve configured fallback policy for genuine primary exhaustion and existing degraded-peer behavior.
- Make a known pre-process failure visible and terminal in the stage journal, release/fence its claim, and allow only bounded same-candidate recovery.
- Preserve fail-closed handling when process-start, process identity, or candidate evidence is ambiguous or the worktree changed.

**Non-Goals:**
- Add providers, change budget/fallback authorization, or loosen capacity checks for stale/unobservable providers.
- Add scheduler services, state machines, DB tables/columns, automatic human approvals, or OpenSpec workflow implementations.
- Deploy Mini Me or execute paid provider calls as part of this proposal.

## Decisions

1. **Separate normal eligibility from peer-outage recovery.** During normal `RUN`, use the persisted primary health status: `AVAILABLE` with no active failure or exhaustion permits Apply regardless of the age of `last_success_at`. Keep the 60-second successful-execution check inside the existing `DRAIN` peer-outage recovery path only. Do not add periodic probes or an inference-consuming probe to make an idle provider eligible. A dispatched invocation remains subject to the ordinary result handling, which records a real failure and updates provider health.

   Alternative rejected: require a fresh successful Apply in normal `RUN`. This reproduces the idle-time blockage documented in Issue #404. Also rejected: ignore active failure/exhaustion signals; the persisted status and current blocking conditions remain mandatory.

2. **Close pre-process failures through the existing stage journal.** When a structured preflight failure proves no workflow process was started, record the terminal invocation result through the existing stage-event/claim path. For a capacity-unavailable result, preserve the Run and checkpoint in the existing capacity-wait path. Do not label a failure safe merely because no process-start event was found: recovery must also have a known preflight failure classification and an unchanged candidate fingerprint.

   Alternative rejected: delete or rewrite the `STARTED` event. The event history is durable evidence and must remain auditable.

3. **Bound automatic recovery and keep ambiguous cases blocked.** Re-enter the same stage only after the prior coordinator has ended, the preflight result proves no child process was created, the candidate/worktree identity is unchanged, and the prior claim is fenced. Permit at most one automatic recovery for this pre-process failure; a repeated failure pauses with its diagnostic. Any evidence of a started/live/unobservable process or changed candidate remains fail-closed. Continue to use the native OpenSpec Apply workflow for all actual implementation work.

   Alternative rejected: mark every exception `PARTIAL` and let scheduler ticks retry indefinitely. That can create a hot loop and bypass the rector's bounded recovery rule.

## Risks / Trade-offs

   - [A persisted `AVAILABLE` status can outlive actual provider capacity] → Do not add paid or inference-consuming idle probes; allow the normal invocation to produce real provider evidence, then persist actual failures and preserve bounded recovery. Active failure/exhaustion signals still block dispatch.
- [An exception may occur after child creation but before the observer persists process identity] → Only classify it as pre-process when the failure source proves it occurred before launch; otherwise preserve the existing fail-closed path.
- [A legitimate transient preflight failure may need more than one automatic recovery] → Keep the existing bounded retry and surface a concrete diagnostic for operator recovery instead of retrying indefinitely.

## Migration Plan

No schema migration is expected. Existing PostgreSQL stage events and claims remain the source of lifecycle evidence. Tests must prove terminal event and claim behavior against PostgreSQL as well as focused capacity logic; rollback is the normal code revert through the project CI/CD process.
