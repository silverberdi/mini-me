# Repository Binding Specification

## Purpose
Prevent any change from becoming executable against a repository other than the one durably registered for its project.

## Requirements

### Requirement: Repository selection is never inferred from presentation metadata
The system SHALL derive execution repository identity only from a validated durable project binding and SHALL NOT authorize execution based on GitHub Project fields, issue titles, labels, or similar presentation data.

#### Scenario: Presentation metadata names another project
- **GIVEN** a durable project binding to repository A
- **WHEN** issue text or GitHub Project display metadata mentions repository B
- **THEN** execution identity remains repository A
- **AND** the presentation metadata does not authorize a repository change.

### Requirement: Binding mismatch blocks readiness
A repository, remote, or project binding mismatch SHALL make the change non-READY and expose a structured reason.

#### Scenario: Issue points at another repository
- **GIVEN** a discovered work item is associated with project A
- **WHEN** its GitHub Issue belongs to repository B
- **THEN** readiness fails with a binding reason
- **AND** no executable workspace target is produced.
