# Structured Review Verdict Specification

## Purpose

Defines the schema, parsing, and validation rules for machine-readable review verdicts and structured issue findings.

## Requirements

### Requirement: Machine-readable review verdict schema
The system SHALL parse and validate reviewer output into an explicit verdict enumeration: `READY_TO_MERGE` or `CHANGES_REQUIRED`.

#### Scenario: Authoritative READY_TO_MERGE verdict
- **WHEN** the reviewer determines all requirements and checks are satisfied without blocking issues
- **THEN** the reviewer emits verdict `READY_TO_MERGE` with an empty findings list
- **AND** the pipeline records the verdict as authoritative.

#### Scenario: Authoritative CHANGES_REQUIRED verdict with findings
- **WHEN** the reviewer detects defects or missing requirements
- **THEN** the reviewer emits verdict `CHANGES_REQUIRED` accompanied by structured findings
- **AND** each finding specifies a severity (`BLOCKER`, `MAJOR`, or `MINOR`), location, violated requirement, and expected correction.

### Requirement: Safe failure on malformed or ambiguous reviewer output
The system SHALL NOT treat malformed, missing, unparseable, or ambiguous reviewer output as `READY_TO_MERGE`.

#### Scenario: Unparseable reviewer output rejected
- **WHEN** a reviewer process exits 0 but outputs non-conforming or unparseable JSON/text
- **THEN** the system SHALL reject the review verdict, mark the review status as `REVIEW_FAILED`, and record a `MALFORMED_REVIEW_OUTPUT` event.
