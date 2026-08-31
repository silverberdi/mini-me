# Queue Prioritization and Admission Specification

## Purpose
Prioritize and admit candidate work items using deterministic scoring, starvation aging, roadmap stage predecessor governance, and capacity admission control.

## Requirements

### Requirement: Deterministic Priority Scoring and Starvation Aging
The system SHALL compute candidate queue priority scores combining base priority (CRITICAL=10000, HIGH=5000, NORMAL=1000, LOW=100), starvation aging bonus (+50/hour capped at 2000), and stage precedence bonus, breaking ties deterministically by stage, discovery timestamp, and issue number.

#### Scenario: Higher declared priority ranks ahead of lower priority
- **GIVEN** two READY items with different declared priorities (CRITICAL vs HIGH)
- **WHEN** priority scores are evaluated
- **THEN** the CRITICAL item SHALL have a higher total score and rank ahead in the candidate queue.

#### Scenario: Long-waiting lower-priority item receives aging bonus
- **GIVEN** a NORMAL item discovered 40 hours ago
- **AND** a NORMAL item discovered just now
- **WHEN** priority scores are evaluated
- **THEN** the older item SHALL receive an aging bonus and rank ahead of the newer item of identical base priority.

### Requirement: Canonical Roadmap Sequence Governance
The system SHALL enforce roadmap sequence order: an OpenSpec change for roadmap stage $N+1$ SHALL NOT be admitted while any predecessor change for stage $N$ remains incomplete or active.

#### Scenario: Future roadmap stage blocked when predecessor incomplete
- **GIVEN** change `017-pwa-control-center` is evaluated for admission
- **AND** change `016-autonomous-queue-work-selection` is currently in progress or unarchived
- **WHEN** `SchedulerService.evaluate_admission()` executes for `017`
- **THEN** admission SHALL be refused with `AdmissionRefusalCode.ROADMAP_PREDECESSOR_INCOMPLETE`.

### Requirement: Admission Concurrency and Capacity Control
The system SHALL enforce scheduler mode (`RUN`/`DRAIN`/`WAIT`), primary implementer availability, global job concurrency limits (`max_global_jobs`), and per-project single-active-implementation rules before admitting work.

#### Scenario: DRAIN mode blocks new change admissions
- **GIVEN** scheduler mode is `DRAIN`
- **WHEN** candidate changes are evaluated for admission
- **THEN** admission SHALL be refused with `AdmissionRefusalCode.PROVIDER_DRAIN`.

#### Scenario: Concurrency limit reached blocks admission
- **GIVEN** `max_global_jobs = 1` and one active execution run is currently in progress
- **WHEN** candidate changes are evaluated for admission
- **THEN** admission SHALL be refused with `AdmissionRefusalCode.GLOBAL_CONCURRENCY_LIMIT`.

### Requirement: Priority Explainability
The system SHALL provide detailed explainability reports (`QueueExplainReport`) breaking down base scores, aging bonuses, blockers, refusal codes, and selection rationale.

#### Scenario: Inspect explainability report for queue item
- **GIVEN** a work item in the queue
- **WHEN** `SchedulerService.explain_item_priority()` is queried
- **THEN** the returned report SHALL include base score, aging bonus, total score, queue position, blockers, and selection rationale.
