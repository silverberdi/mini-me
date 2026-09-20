# Proposal: Autonomous Intake Preparation & Admission Policy

## Problem Statement
The current mini me work intake flow requires unnecessary manual operator ceremony:
1. Operator creates a Work Item in the backlog.
2. Operator must manually click "Prepare Artifacts" to trigger OpenSpec generation, GitHub issue creation, and DoR assessment.
3. Operator must manually inspect readiness.
4. Operator must manually click "Start Work" to admit the change into the autonomous scheduler.

This ceremony creates operational friction and prevents unattended end-to-end delivery of backlog items.

## Proposed Change
Deliver a policy-driven autonomous happy path that automatically transitions work from backlog creation to scheduled execution:
```
Create Backlog Item
-> automatic canonical preparation
-> automatic OpenSpec artifact generation
-> automatic Definition of Ready (DoR) evaluation
-> READY state
-> automatic admission according to project policy
-> scheduler execution (Run/Job)
-> implementation -> checks -> review -> audit -> PR
-> human merge gate
-> native post-merge closure
-> automatically evaluate backlog and admit next item
```

The operator intervenes ONLY for:
- Genuine product ambiguity (`NEEDS_HUMAN` gate);
- Explicit provider/cost decisions;
- Mandatory human merge authorization;
- Exceptional safety/recovery overrides.

## Acceptance Criteria
1. Creating a valid backlog item automatically starts preparation when `auto_prepare` is true.
2. Normal happy path requires 0 manual "Prepare Artifacts" or "Start Work" clicks.
3. GitHub Issue, GitHub Project item, OpenSpec change artifacts, and ProjectBinding are created/synchronized automatically.
4. Definition of Ready is evaluated automatically; well-specified items transition to `READY`.
5. Underspecified items transition to `NEEDS_HUMAN` with a minimal product question, and resume preparation when answered.
6. Project admission policy is configurable with canonical defaults: `auto_prepare = true`, `auto_admit = true`, `max_concurrent_jobs = 1`.
7. READY eligible work is automatically admitted when a concurrency slot and required primary provider are available.
8. READY work is held in waiting state without consuming retries or using OpenRouter when the primary provider is unavailable.
9. OpenRouter drain policy strictly forbids starting new work.
10. Provider recovery probing automatically triggers admission once the primary provider recovers.
11. Backlog selection is deterministic, prioritize by priority and dependency topology, and provides observable selection reasons.
12. After an item completes and releases its concurrency slot, the scheduler automatically evaluates the backlog and admits the next eligible item.
13. Excluded states (`DRAFT`, `NEEDS_HUMAN`, `BLOCKED`, paused work) are never auto-admitted.
14. Manual "Prepare Artifacts" and "Start Work" remain accessible for recovery, manual-policy overrides, and exceptional actions.
15. PWA and TUI display preparation state, readiness state, policy settings, admission eligibility, and waiting reasons clearly.
16. All preparation, readiness, and admission transitions persist auditable structured events.
17. Repeated scheduler cycles are strictly idempotent (zero duplicate Issues, Project items, OpenSpec changes, Runs, or Jobs).

## Non-Goals
- Autonomous product ideation (mini me executes operator-defined backlog intent; it does not invent new unapproved backlog work).
- Multi-job concurrency beyond the configured limit (`max_concurrent_jobs = 1` in initial proving).
- Automatic merging (human merge authorization remains mandatory).
- Bypassing deterministic checks, complementary review, or DeepSeek audit.
