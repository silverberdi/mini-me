## ADDED Requirements

### Requirement: Evidence-linked SRE improvement proposals
The system SHALL allow a supported recurring technical root cause or newly required tool observed by SRE interventions to produce a formal, evidence-linked proposal for an adjustment to the SRE Unblocker skill or playbook. Proposals SHALL be recorded in the existing Mejora Continua feed with source Run/intervention references and remain subject to operator handling; the system SHALL NOT create or submit a GitHub Issue autonomously.

#### Scenario: Supported recurrence produces a proposal
- **WHEN** multiple immutable intervention facts establish a recurring root cause or a verified need for a tool
- **THEN** the system records a proposed skill/playbook adjustment with its evidence references in Mejora Continua
- **AND** an operator can inspect and handle it through the existing feed

#### Scenario: Insufficient evidence does not create a proposal
- **WHEN** recurrence or tool need is based on a single unsupported observation or ambiguous evidence
- **THEN** the system does not present it as an established pattern or formal proposal

#### Scenario: Proposal is eligible for external tracking
- **WHEN** an operator chooses to track a supported improvement as work
- **THEN** the system provides the proposal for operator-controlled GitHub Issue creation or an eligible issue reference
- **AND** no GitHub mutation occurs without that operator action
