## MODIFIED Requirements

### Requirement: Machine-readable review verdict schema
The system SHALL parse and validate reviewer output into an explicit verdict enumeration: `READY_TO_MERGE` or `CHANGES_REQUIRED`, and SHALL validate reviewer missing-file finding claims against explicit OpenSpec contracts, the frozen `CandidateManifest`, and the authoritative candidate tree at the exact candidate SHA (supported by base..candidate diff analysis) before accepting a blocker finding.

#### Scenario: Authoritative READY_TO_MERGE verdict
- **WHEN** the reviewer determines all requirements and checks are satisfied without blocking issues
- **THEN** the reviewer emits verdict `READY_TO_MERGE` with an empty findings list
- **AND** the pipeline records the verdict as authoritative.

#### Scenario: Authoritative CHANGES_REQUIRED verdict with findings
- **WHEN** the reviewer detects defects or missing requirements
- **THEN** the reviewer emits verdict `CHANGES_REQUIRED` accompanied by structured findings
- **AND** each finding specifies a severity (`BLOCKER`, `MAJOR`, or `MINOR`), location, violated requirement, and expected correction.

#### Scenario: Required unchanged base file verified present in candidate tree
- **WHEN** a reviewer emits a `BLOCKER` finding claiming that an existing repository file is missing because it does not appear in the base..candidate diff
- **AND** the authoritative candidate tree at the exact candidate SHA proves the file is present and unmodified
- **THEN** the system SHALL reject the missing-file claim as invalid and prevent a false blocker transition.

#### Scenario: Real missing file required by spec fails normally
- **WHEN** a reviewer emits a `BLOCKER` finding claiming a file explicitly required by OpenSpec tasks or specifications is missing
- **AND** the authoritative candidate tree and manifest confirm the required file is absent from the candidate tree
- **THEN** the system SHALL accept the finding as a valid blocker and route to continuation remediation.

#### Scenario: Guessed filename absent from candidate tree rejected as blocker
- **WHEN** a reviewer emits a `BLOCKER` finding asserting that a non-contractual, guessed, or convention-based filename is missing
- **AND** the capability is satisfied by alternative candidate modules or the file is not required by OpenSpec contracts
- **THEN** the system SHALL classify the finding as a false blocker / non-blocking remark and reject the blocking claim.
