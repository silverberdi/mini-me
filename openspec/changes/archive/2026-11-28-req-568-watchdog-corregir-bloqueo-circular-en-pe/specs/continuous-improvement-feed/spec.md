# Spec Delta

## MODIFIED Requirements

### Requirement: Cross-project improvement feed
The system SHALL provide an authenticated `Mejora Continua` view at `/mejora-continua` over persisted Watchdog suggestions, with project and status filters, root cause, affected component, source run, and evidence-bound summary. The authenticated administration endpoint `/api/v1/admin/watchdog/diagnoses` SHALL return persisted diagnoses that have an improvement suggestion, including the suggestion, its source diagnosis and evidence, and its current status. A newly cataloged Watchdog suggestion SHALL be returned with status `pending` and SHALL be visible to the `Mejora Continua` view. The feed SHALL expose only sanitized data authorized for the operator and SHALL distinguish pending, converted-to-draft, and discarded suggestions.

#### Scenario: Browse and filter suggestions
- **WHEN** the operator opens the feed and filters by a project or status
- **THEN** the view returns only matching persisted suggestions with their project and source-run identity
- **AND** an empty result is shown as empty rather than populated with inferred patterns

#### Scenario: Persisted pending diagnosis appears in administration
- **WHEN** an authorized operator requests `/api/v1/admin/watchdog/diagnoses` after Watchdog has persisted a diagnosis with an improvement suggestion
- **THEN** the response includes the diagnosis, its source event and transition or intervention identity, the suggestion, and status `pending`
- **AND** the same persisted suggestion is available to `/mejora-continua`

#### Scenario: Show recurrent patterns
- **WHEN** multiple persisted suggestions have the same supported root-cause classification and affected component
- **THEN** the feed may summarize that observed recurrence with its actual count and linked source records
- **AND** it does not claim a pattern from missing or ambiguous evidence

### Requirement: Operator-controlled suggestion handling
The system SHALL let an authorized operator copy a formatted suggestion as an Issue draft or discard it. Copying SHALL mark it converted-to-draft only after the copy action succeeds; discarding SHALL persist the discarded status. Neither action SHALL create, edit, or close a GitHub Issue.

#### Scenario: Copy suggestion as a draft
- **WHEN** the operator chooses to copy a pending suggestion and the clipboard action succeeds
- **THEN** the formatted draft is copied and the suggestion becomes converted-to-draft
- **AND** no GitHub API mutation occurs

#### Scenario: Clipboard action fails
- **WHEN** the operator requests a copy but the browser denies or fails the clipboard operation
- **THEN** the suggestion remains pending
- **AND** the UI reports that the draft was not copied

#### Scenario: Discard suggestion
- **WHEN** the operator discards a pending suggestion
- **THEN** its discarded state is persisted and reflected in the feed
- **AND** its source diagnosis and evidence remain available for audit

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
