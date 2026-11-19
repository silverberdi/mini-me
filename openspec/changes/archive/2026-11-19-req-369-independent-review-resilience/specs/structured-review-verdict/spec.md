## ADDED Requirements

### Requirement: Diagnostic observability for malformed reviewer output
The system SHALL capture and persist the prefix and suffix of the unparseable reviewer raw output upon review parse failure to provide immediate diagnostic visibility in run details and operational logs without speculative troubleshooting.

#### Scenario: Parse failure persists raw response diagnostics
- **WHEN** the review verdict parser fails to locate a valid structured verdict in the reviewer output
- **THEN** the orchestrator captures the first 500 characters and last 500 characters of the raw reviewer output
- **AND** stores this diagnostic snippet in `stop_details` and review diagnostic records
- **AND** surfaces it in the human gate / operational view for immediate inspection.
