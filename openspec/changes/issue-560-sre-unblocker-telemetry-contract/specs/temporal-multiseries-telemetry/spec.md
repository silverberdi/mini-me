## ADDED Requirements

### Requirement: Autonomy intervention outcome visibility
The autonomy projection SHALL distinguish eligible completed Runs that completed without an intervention, completed after an autonomous SRE intervention, and required operator action. It SHALL derive these categories only from complete, immutable intervention and operator-action evidence linked to the Run; existing aggregate autonomy semantics SHALL continue to count a successful autonomous recovery as autonomous. Incomplete or contradictory evidence SHALL be excluded from classification and surfaced as unverified/no-data rather than guessed.

#### Scenario: Clean run and autonomous recovery are distinguished
- **WHEN** completed Runs have evidence respectively showing no intervention and a successful autonomous SRE intervention with no operator action
- **THEN** the projection exposes separate counts for clean completion and autonomous recovery
- **AND** both remain in the autonomous share under the existing autonomy definition

#### Scenario: Operator-needed run is identified
- **WHEN** a completed Run has evidence of operator action or a human-gate response
- **THEN** the projection identifies it as requiring operator action
- **AND** includes it in the existing eligible completed-run denominator as operator-assisted

#### Scenario: Intervention evidence is missing or contradictory
- **WHEN** a Run has an intervention record without a conclusive result, or its intervention and operator-action evidence conflict
- **THEN** the projection excludes it from the outcome categories and autonomy percentage
- **AND** reports it as unverified rather than inferring success or autonomy
