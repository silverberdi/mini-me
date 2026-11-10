## MODIFIED Requirements

### Requirement: Safe failure on malformed or ambiguous reviewer output
The system SHALL NOT treat malformed, missing, unparseable, or ambiguous reviewer output as `READY_TO_MERGE`. The system SHALL robustly extract structured JSON review verdicts with arbitrary nesting depth and nested curly braces in string literals using standard JSON stream decoding, without misidentifying valid findings as malformed output.

#### Scenario: Unparseable reviewer output rejected
- **WHEN** a reviewer process exits 0 but outputs non-conforming or unparseable JSON/text
- **THEN** the system SHALL reject the review verdict, mark the review status as `REVIEW_FAILED`, and record a `MALFORMED_REVIEW_OUTPUT` event.

#### Scenario: Valid verdict containing nested braces and CSS literals parsed cleanly
- **WHEN** a reviewer outputs a structured JSON review verdict containing nested arrays, objects, or string literals with curly braces (such as CSS or code rules)
- **THEN** the system SHALL successfully decode the root payload into `ReviewVerdictPayload`
- **AND** the system SHALL preserve all findings without misclassifying the output as malformed.
