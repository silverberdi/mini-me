# Design: Autonomous Intake Preparation & Admission Policy

## Architectural Approach
This change transitions mini me from manual human-initiated work preparation and admission to an autonomous, policy-driven intake pipeline while preserving human merge authority and strict isolation invariants.

```
+---------------------+
| Backlog Item Create |
+----------+----------+
           | (auto_prepare = True)
           v
+---------------------+     (ambiguous)      +---------------+
| Automatic Artifact  | -------------------> |  NEEDS_HUMAN  |
| Preparation (Issue, |                      +-------+-------+
| Project, OpenSpec)  |                              | (answer)
+----------+----------+ <----------------------------+
           | (DoR valid)
           v
+---------------------+
|     READY Item      |
+----------+----------+
           |
           v (Scheduler Tick)
+--------------------------------------------------------+
| Admission Policy Evaluator:                            |
| 1. Active runs < max_concurrent_jobs (default: 1)      |
| 2. Dependencies satisfied                              |
| 3. Primary provider AVAILABLE                          |
| 4. Deterministic Backlog Ranking (Priority / Age)      |
+--------------------------+-----------------------------+
                           | (Eligible)
                           v
+--------------------------------------------------------+
| Orchestration Admission -> Run / Job Execution Pipeline|
+--------------------------------------------------------+
```

## Key Components

### 1. Project Admission Policy Settings
Extend `Project` domain model and schema with:
- `auto_prepare: bool = True`
- `auto_admit: bool = True`
- `max_concurrent_jobs: int = 1`

### 2. Auto-Preparation in IntakeService
- `IntakeService.create_work_item()`: If `project.auto_prepare` is true, immediately execute `prepare_work_item()`.
- If requirements are complete, transition item to `WorkItemStatus.READY`.
- If requirements are ambiguous, transition to `WorkItemStatus.NEEDS_HUMAN` and record `human_questions`.
- `IntakeService.answer_human_question()`: Automatically re-triggers `prepare_work_item()`.

### 3. Auto-Admission in SchedulerService
- During each periodic `SchedulerService.tick()`:
  - Check active runs count for the project against `project.max_concurrent_jobs`.
  - Retrieve all `READY` backlog items for the project.
  - Check primary provider availability via `ProviderHealthService` / generic provider adapter.
  - If provider is unavailable, keep eligible work in `READY` waiting status with explicit diagnostic waiting reason (no OpenRouter starter fallback).
  - If concurrency slot is available and primary provider is `AVAILABLE`:
    - Select top-ranked eligible item (`select_next_admissible_work_item()`).
    - Autonomously invoke `OrchestrationService.admit_change()`.
    - Transition `BacklogItem.status` to `RUNNING` with `run_id`.
    - Persist `SchedulerDecisionRecord` and `Event` audit trail.

### 4. PWA & TUI Observability
- Update PWA Backlog & Intake view to render:
  - Policy summary badge (`Auto-Prepare: ON`, `Auto-Admit: ON`, `Concurrency: 1`).
  - Admission status pill (`READY (Awaiting Slot)`, `READY (Awaiting Provider Capacity)`, `READY (Eligible)`).
  - Ranked priority order.
- TUI queue/changes views expose admission eligibility and policy status.

## Trade-offs & Invariants
- **Concurrency Guard**: Default concurrency is strictly 1. Multi-job execution is bounded by `max_concurrent_jobs`.
- **Zero LLM Overhead**: Deterministic parsing, artifact authoring, DoR calculation, and admission selection consume 0 LLM tokens.
- **Provider Agnostic**: Admission depends on generic provider adapter status (`ProviderAdapterInterface`), not hardcoded provider branching.
