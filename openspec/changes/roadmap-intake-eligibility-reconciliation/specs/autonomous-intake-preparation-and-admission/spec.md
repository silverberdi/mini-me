## ADDED Requirements

### Requirement: Roadmap preparation eligibility
The system SHALL prepare a ROADMAP backlog item autonomously only when current pure roadmap evidence projects it as READY. NEXT/BACKLOG, BLOCKED, and COMPLETED/DONE roadmap projections SHALL not be selected by autonomous intake. Non-ROADMAP backlog selection SHALL retain its existing behavior.

#### Scenario: Future roadmap projection is not swept
- **WHEN** a ROADMAP item is BACKLOG and NOT_READY
- **THEN** autonomous intake does not prepare it

#### Scenario: Local backlog remains eligible
- **WHEN** a LOCAL_BACKLOG item is BACKLOG and NOT_READY
- **THEN** existing autonomous preparation selection applies

### Requirement: Explicit roadmap list identity
The system SHALL recognize a roadmap list item only when its prefix is an explicit numeric/stage-prefixed key. It SHALL not create a work item from a prose bullet such as `Multi-repository project binding & fleet validation.`.

#### Scenario: Prose bullet is ignored
- **WHEN** the roadmap contains `- Multi-repository project binding & fleet validation.`
- **THEN** pure discovery returns no `Multi` item
