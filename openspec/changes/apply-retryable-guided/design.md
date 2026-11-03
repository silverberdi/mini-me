## Context

See proposal.md for motivation and the delta spec for required behavior. The existing Apply coordinator returns a boolean; its callers route success to Verify and failure to retry/block. The current native Apply and Verify contract remains authoritative for workflow invocation and testing.

## Goals / Non-Goals

**Goals:** derive retry decisions from observed task, Git, test, and candidate evidence; retain the existing candidate across bounded native workflow invocations.

**Non-Goals:** implement OpenSpec semantics, change Archive or human-question UI behavior, add a new provider or persistent subsystem.

## Decisions

- Return a typed outcome from Apply and update every caller. Capture changed paths and candidate identity from Git and run the coordinator's relevant test pass; treat agent text as workflow output, not proof of tests or implementation.
- Compare consecutive outcomes: progress is fewer pending automatic tasks or changed candidate identity with a non-empty diff. A human-required result is surfaced with original options and does not spend an attempt. Terminal failures follow existing authorized escalation.
- On partial progress, invoke native Apply with a factual recovery context that explicitly separates recovery evidence from reviewer `corrections`. Use native Continue only when the installed workflow reports a resumable operation.
- Apply the configured no-progress limit, hard total attempt cap, correction limit, and budget before dispatch. Stop on candidate identity change or evidence of regression; do not infer an unreported rationale.
- Accept task completion only when coordinator-observed diff and passing relevant tests support it. If evidence is insufficient, leave the task pending and fail closed.
- Exercise orchestration deterministically with a simulated Apply result sequence. Label this as deterministic orchestration evidence, not a real-agent E2E invocation.

## Risks / Trade-offs

- [A whole-suite test pass after each attempt may be costly] → run the relevant project test command and honor existing budget limits.
- [Diff presence alone may not prove a task complete] → require both observed implementation diff and passing relevant tests for checkbox acceptance.
- [Task checkbox changes can be mistaken for implementation progress] → compare task counts separately and require candidate/diff evidence as specified.
