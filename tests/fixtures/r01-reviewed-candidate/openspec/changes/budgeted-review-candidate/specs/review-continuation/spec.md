# Review continuation

## ADDED Requirements

### Requirement: Continue a reviewed candidate through existing gates

The system SHALL resume an exactly bound frozen candidate after an explicit post-review action.

#### Scenario: Resume the frozen candidate

- **WHEN** the persisted review is complete and the action identity matches the candidate
- **THEN** the existing downstream gates receive the same candidate SHA
