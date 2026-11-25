# continuous-improvement-feed Specification

## Purpose

Give operators a cross-project view of persisted, evidence-backed recurrence-prevention suggestions and let them handle each suggestion without creating GitHub work autonomously.

## Requirements

### Requirement: Cross-project improvement feed
The system SHALL provide an authenticated `Mejora Continua` view at `/mejora-continua` over persisted Watchdog suggestions, with project and status filters, root cause, affected component, source run, and evidence-bound summary. The feed SHALL expose only sanitized data authorized for the operator and SHALL distinguish pending, converted-to-draft, and discarded suggestions.

#### Scenario: Browse and filter suggestions
- **WHEN** the operator opens the feed and filters by a project or status
- **THEN** the view returns only matching persisted suggestions with their project and source-run identity
- **AND** an empty result is shown as empty rather than populated with inferred patterns

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
