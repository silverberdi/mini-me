## MODIFIED Requirements

### Requirement: Grounded Complexity Evaluation
Following successful strict validation and a passing task-executability assessment, the thinking agent SHALL evaluate the change complexity as `low`, `moderate`, or `high` based on architectural scope, risk, and touchpoints through an LLM evaluation prompt, recording its rationale in durable state. Complexity SHALL NOT be determined via deterministic keyword regex or static heuristic rules.

#### Scenario: Low or moderate complexity proceeds directly to Apply
- **GIVEN** a strictly validated OpenSpec change with every task assessed executable
- **WHEN** the thinking agent evaluates the change as `low` or `moderate`
- **THEN** the run records the complexity verdict and transitions directly to `READY TO APPLY`, skipping independent proposal review.

#### Scenario: High complexity mandates independent proposal review
- **GIVEN** a strictly validated OpenSpec change with every task assessed executable
- **WHEN** the thinking agent evaluates the change as `high`
- **THEN** the run transitions to `PROPOSAL_REVIEW`, mandating independent reviewer evaluation before Apply.

## ADDED Requirements

### Requirement: Evidence-backed task executability before proposal acceptance
After native Propose and strict validation, and before complexity evaluation or proposal review, the system SHALL assess every OpenSpec task required for delivery. Each assessment SHALL identify the task, responsible actor, currently available capability, any required external precondition, and observable completion evidence, all tied to repository or project evidence. A proposal SHALL advance only when every task has an executable path using capabilities and preconditions confirmed for that project and workflow. An unknown capability, unconfirmed human participant, unmet external dependency, or missing evidence SHALL keep the proposal unaccepted and prevent Apply from starting or consuming an Apply attempt. A project CI/CD deployment that occurs only after PR merge SHALL NOT count as candidate preview capability before Apply or Verify. The system SHALL NOT add deployment capability to Mini Me, mark tasks complete, or allow free-text authorization to override an unmet precondition. The active gate SHALL explain each blocked task and the evidence needed to re-evaluate it. After the Request or project capability evidence changes, the system SHALL re-run native OpenSpec Update/strict validation as applicable and re-assess executability against the resulting artifacts before advancing.

#### Scenario: All tasks have confirmed executable paths
- **GIVEN** a strictly validated proposal whose tasks each identify an available actor and capability, satisfied preconditions, and observable evidence
- **WHEN** executability is assessed before complexity or review
- **THEN** the assessment is persisted against the exact proposal artifact hashes and project capability evidence
- **AND** the workflow proceeds to complexity evaluation.

#### Scenario: Candidate validation requires unavailable preview deployment
- **GIVEN** a task requires testing the candidate in a preview deployment before Apply or Verify
- **AND** the project repository has no verified preview deployment available before merge for that candidate SHA
- **WHEN** task executability is assessed
- **THEN** the proposal remains unaccepted at the current human gate
- **AND** Apply is not invoked and no Apply attempt is consumed
- **AND** the gate identifies the deployment dependency and the evidence needed to satisfy it or revise the Request scope.

#### Scenario: Human-only evidence has no confirmed participant or available candidate
- **GIVEN** a proposed task requires physical-device testing or an observation session
- **AND** the candidate is not available to that participant or the responsible participant is not confirmed
- **WHEN** task executability is assessed
- **THEN** the proposal remains unaccepted
- **AND** the system does not treat the task as work an automated Apply agent can complete.

#### Scenario: Missing or unverifiable capability evidence fails closed
- **GIVEN** an assessment omits a task, names an unconfigured actor, cites an absent capability, or cannot verify a required precondition
- **WHEN** the assessment is validated
- **THEN** the proposal remains unaccepted with the exact evidence gap
- **AND** a free-text operator response alone cannot advance it.

#### Scenario: Updated Request or capability evidence allows reassessment
- **GIVEN** a proposal is held because a required precondition is unavailable
- **AND** the original Request or project capability evidence is updated and verified
- **WHEN** the native proposal artifacts are updated and strictly validated
- **THEN** the system re-assesses every task against the new artifact and capability evidence hashes
- **AND** advances only if every required task now has a confirmed executable path.
