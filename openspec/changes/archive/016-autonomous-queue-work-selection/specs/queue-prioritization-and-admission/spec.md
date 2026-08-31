# Queue Prioritization and Admission Specification

## ADDED Requirements

### Requirement: Deterministic Prioritization and Explainability
The system SHALL compute candidate queue priority scores using an explicit, deterministic formula combining base priority level, starvation aging bonuses, and roadmap precedence, without utilizing non-deterministic LLM scoring authority.

#### Scenario: Priority ordering across priority levels
Given two READY queue items for the same roadmap stage: Item A with `priority="HIGH"` and Item B with `priority="NORMAL"`
When the scheduler ranks candidate items
Then Item A SHALL be ranked ahead of Item B
And the explainability report SHALL attribute the ranking difference to the higher base priority score.

#### Scenario: Starvation prevention aging
Given an eligible Item C with `priority="NORMAL"` discovered 48 hours ago
And an eligible Item D with `priority="NORMAL"` discovered 1 hour ago
When the scheduler computes priority scores
Then Item C SHALL receive an aging bonus and rank ahead of Item D.

### Requirement: Canonical Roadmap Stage Governance
The system SHALL enforce strict roadmap stage progression such that work items belonging to roadmap stage $N+1$ MUST NOT be admitted if any predecessor stage $N$ is incomplete, refusing admission with reason `ROADMAP_PREDECESSOR_INCOMPLETE`.

#### Scenario: Block future roadmap stage when predecessor incomplete
Given an OpenSpec change `017-pwa-control-center` belonging to roadmap stage 17
And current roadmap stage 16 `016-autonomous-queue-work-selection` is not yet completed/merged
When the scheduler evaluates `017-pwa-control-center` for admission
Then the scheduler SHALL refuse admission
And record a decision with `decision="REFUSED"` and `reason_code="ROADMAP_PREDECESSOR_INCOMPLETE"`.

### Requirement: Dependency Graph Resolution
The system SHALL evaluate declared change dependencies, permitting admission only when all declared dependency changes are completed/archived and rejecting cyclical dependency graphs.

#### Scenario: Block admission when dependency is incomplete
Given change `016-subtask-b` declaring dependency on `016-subtask-a`
And `016-subtask-a` is currently in progress
When the scheduler evaluates `016-subtask-b`
Then the scheduler SHALL refuse admission with `reason_code="DEPENDENCY_BLOCKED"`.

#### Scenario: Permit admission when dependency is completed
Given change `016-subtask-b` declaring dependency on `016-subtask-a`
And `016-subtask-a` has completed all DOD gates and is archived
When the scheduler evaluates `016-subtask-b`
Then the dependency check SHALL pass.

### Requirement: Provider Capacity and Concurrency Gating
The system SHALL enforce scheduler modes (`RUN`, `DRAIN`, `WAIT`), global active run limits (`max_global_jobs`), and per-project active run limits (`one_active_implementation_per_project`), refusing admission when limits are reached or providers are unavailable.

#### Scenario: Block admission in DRAIN mode
Given scheduler mode is set to `DRAIN`
When a new READY work item is evaluated for admission
Then the scheduler SHALL refuse admission with `reason_code="PROVIDER_DRAIN"`
And allow existing in-flight jobs to continue.

#### Scenario: Block admission when global concurrency limit reached
Given `max_global_jobs = 1`
And one orchestration run is currently active in stage `IMPLEMENTING`
When a new eligible READY work item is evaluated
Then the scheduler SHALL refuse admission with `reason_code="GLOBAL_CONCURRENCY_LIMIT"`.

### Requirement: Atomic Transactional Admission
The system SHALL execute admission evaluations within an atomic database transaction using concurrency locks, guaranteeing that concurrent scheduler ticks or repeated evaluations never create duplicate orchestration runs or duplicate execution jobs.

#### Scenario: Concurrent admission attempts admit exactly once
Given two scheduler instances concurrently evaluating the same READY work item
When both execute the admission evaluation simultaneously
Then exactly one instance SHALL successfully admit the item and create an `OrchestrationRun`
And the other instance SHALL detect the existing run and record `ALREADY_ADMITTED` without duplicating side effects.
