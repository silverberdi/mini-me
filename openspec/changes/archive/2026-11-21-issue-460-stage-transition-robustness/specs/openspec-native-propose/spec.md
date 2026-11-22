## ADDED Requirements

### Requirement: Approved proposal corrections refresh the reviewed feasibility baseline
After an authorized proposal correction is accepted by the independent reviewer, the system SHALL bind the task and scenario reference hashes used for subsequent stage checks to the exact approved proposal artifacts. The approval record and refreshed reference hashes SHALL be persisted atomically in the same PostgreSQL transaction; a restart SHALL NOT leave one persisted without the other. Before advancing, it SHALL re-run the existing strict OpenSpec validation and feasibility checks against that version. A hash refresh SHALL NOT by itself certify changed task/scenario inventories, mappings, or execution preconditions; unresolved or newly changed feasibility evidence SHALL continue to block advancement.

#### Scenario: Approved wording correction does not create a false drift gate
- **GIVEN** an independent reviewer requested a proposal correction and approved the corrected proposal
- **AND** the corrected task and scenario inventory remains feasible under the existing assessment
- **WHEN** the Run checks readiness to advance
- **THEN** it records the reference hashes of the exact reviewer-approved artifacts
- **AND** it persists those hashes in the same transaction as the approval of that review result
- **AND** it does not raise a drift gate solely because those approved artifacts differ from their pre-review hashes
- **AND** it retains the existing strict validation and feasibility evidence.

#### Scenario: Review approval and hash refresh commit atomically
- **GIVEN** a corrected proposal has been approved and its reference hashes are ready to persist
- **WHEN** PostgreSQL commits or rolls back the review result
- **THEN** the approval and refreshed hashes are both durable or neither is durable
- **AND** recovery does not observe a mixed state that treats an uncommitted approval or hash refresh as authoritative.

#### Scenario: Approved correction changes feasibility-relevant content
- **GIVEN** a reviewer-approved correction changes task/scenario identities, their mapping, or a task's execution preconditions
- **WHEN** the Run checks readiness to advance
- **THEN** it re-evaluates the affected feasibility evidence against the approved artifacts
- **AND** it remains blocked if the changed content is missing, invalid, or not executable
- **AND** it does not treat refreshed hashes alone as approval of the changed feasibility.

### Requirement: Native Propose prompts require a scenario for each delta-spec requirement
The native Propose instruction SHALL explicitly remind the configured thinking agent that every `Requirement` in every delta specification must include at least one `#### Scenario:` block. The system SHALL continue to use the installed native OpenSpec workflow and strict OpenSpec CLI validation as the authorities for artifact creation and validity; the prompt reminder SHALL NOT replace or weaken those checks.

#### Scenario: Propose is instructed to include scenarios for every requirement
- **GIVEN** the system prepares the prompt for a native OpenSpec Propose invocation
- **WHEN** the prompt is dispatched to the configured thinking agent
- **THEN** it explicitly requires at least one scenario under every requirement in each delta specification
- **AND** the resulting change is still checked by the strict OpenSpec CLI validator before it advances.

#### Scenario: Missing scenario remains invalid after the prompt reminder
- **GIVEN** a proposed delta specification contains a requirement without a scenario
- **WHEN** strict OpenSpec validation evaluates the change
- **THEN** the change does not pass validation or advance as valid
- **AND** the system reports the validator's observed diagnostic without fabricating a passing result.
