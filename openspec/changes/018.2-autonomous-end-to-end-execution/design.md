# Design: 018.2 — Autonomous End-to-End Execution

## Architectural Overview
018.2 establishes a self-driving execution loop across the canonical 15 SDLC phases:
1. `WorkDiscoveryService.discover_work()`
2. `ReadinessService.evaluate_change_readiness()`
3. `SchedulerService.evaluate_admission()`
4. `SchedulerService.admit_work_item()` -> `OrchestrationService.admit_change()`
5. `ProviderPolicyService.evaluate_selection()` (Codex default workhorse)
6. `WorktreeManager.create_worktree()`
7. `ExecutionPipelineService.execute_queued_job()`
8. `ContinuationEngine` & remediation routing
9. `OrchestrationService.FREEZING_CANDIDATE`
10. `ChecksRunner.run()`
11. `ReviewerRunner.run()` & `AuthorshipService.is_reviewer_eligible()` (Rule G)
12. `DeepSeekAuditorRunner.run()`
13. `ContainerPreviewService` / `ValidationAuthorityService` (when UI-affecting)
14. `OrchestrationService.PREPARING_PR` (Git branch push + GitHub PR create/adopt)
15. `OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE`

```
 [READY Work]
      │
      ▼
 [Discovery & Admission] ──► [Run & Job Creation]
                                    │
                                    ▼
                             [Worktree Setup]
                                    │
                                    ▼
                             [Implementation (Codex)]
                                    │
                   ┌────────────────┴────────────────┐
                   ▼                                 ▼
             [Checks Pass]                    [Checks Fail / Findings]
                   │                                 │
                   ▼                                 ▼
            [Candidate Freeze]               [Remediation Loop]
                   │                                 ▲
                   ▼                                 │
         [Independent Review] ──(Changes Req)────────┤
                   │                                 │
                   ▼                                 │
          [DeepSeek Audit] ──────(Blocked)───────────┘
                   │
                   ▼
          [Native PR Creation]
                   │
                   ▼
       [READY_FOR_HUMAN_MERGE]
```

## State Machine Hardening
The orchestration driver evaluates the active `OrchestrationRun` deterministically:
- `ADMITTED -> PREPARING_EXECUTION -> IMPLEMENTING -> EVALUATING_ATTEMPT -> RUNNING_CHECKS -> FREEZING_CANDIDATE -> COMPLEMENTARY_REVIEW -> INDEPENDENT_AUDIT -> PREPARING_PR -> PR_PREPARED -> READY_FOR_HUMAN_MERGE`.
- Remediation Transitions:
  - If deterministic checks fail: `RUNNING_CHECKS -> EVALUATING_ATTEMPT -> IMPLEMENTING`.
  - If review requires changes: `COMPLEMENTARY_REVIEW -> REVIEW_REMEDIATION -> IMPLEMENTING`.
  - If audit finds blocker/critical findings: `INDEPENDENT_AUDIT -> AUDIT_REMEDIATION -> IMPLEMENTING`.
- Terminal / Waiting States:
  - `WAITING_CAPACITY`: provider quota/concurrency exhaustion.
  - `WAITING_EXTERNAL`: transient GitHub remote unobservability.
  - `READY_FOR_HUMAN_MERGE`: candidate PR prepared and waiting for human merge authorization.

## Prompt Context Enhancement for Remediation
When re-entering `IMPLEMENTING` after checks failure, review findings, or audit failure:
- `ExecutionPipelineService` formats any structured `ReviewFinding` items into explicit corrective instructions.
- `ExecutionPipelineService` formats any `AuditFinding` items into explicit corrective instructions.
- `ExecutionPipelineService` formats failing check diagnostics into the prompt context.

## PR Creation and Reconciled Adoption
In `PREPARING_PR`:
1. Reconcile remote branch head:
   - If remote branch head == audited candidate SHA -> mark push COMPLETED without redundant push.
   - If remote branch does not exist -> execute push once and verify remote ref.
   - If remote branch exists with a different SHA -> fail closed `NEEDS_HUMAN` to prevent overwriting unverified code.
2. Reconcile GitHub PR:
   - Lookup existing open/closed PRs on `minime/<change_name>`.
   - If matching PR exists with exact candidate head SHA and base branch -> adopt PR, record number and URL in `ProjectBinding`.
   - If no PR exists -> create PR linking canonical issue (`Closes #<issue_number>`).
   - Transition run to `PR_PREPARED` and stop at `READY_FOR_HUMAN_MERGE`.

## Database & Schema Invariants
- PostgreSQL remains the sole operational database.
- Physical schema invariant check verifies Alembic head `016_provider_efficiency_telemetry`.
