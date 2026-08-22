## Purpose

Guarantees candidate worktree visibility proof for reviewers through comprehensive file manifests, and provides a machine-readable evidence diagnostic model separating environmental execution inability from code defects.

## ADDED Requirements

### Requirement: Comprehensive candidate worktree manifest generation
The system SHALL generate a cryptographic and structural candidate manifest before launching review or audit, enumerating all tracked modifications, staged files, untracked candidate files, deleted files, candidate commit SHA, worktree path, and validated repository identity.

#### Scenario: Manifest captures untracked and modified candidate files
- **WHEN** implementation completes and deterministic checks run
- **THEN** the system SHALL construct a candidate manifest listing every modified and untracked file in the worktree along with file sizes and content hashes, persisting the manifest in PostgreSQL.

### Requirement: Reviewer candidate visibility verification and diagnostic
The system SHALL verify that the complementary reviewer process has complete visibility of all files listed in the candidate manifest before accepting review findings. If the reviewer's snapshot or environment cannot access all manifest files, the system SHALL record an evidence diagnostic of `REVIEW_ENVIRONMENT_INVALID` on the review execution record. The system SHALL NOT accept the review outcome as authoritative, SHALL NOT transition the job to review failure or code defect states, and SHALL trigger a continuation decision of `WAIT_EXTERNAL` (if environment reconciliation is possible) or `NEEDS_HUMAN`.

#### Scenario: Reviewer blindness to candidate files detected
- **WHEN** a reviewer reports a missing file or test finding for an artifact that is confirmed present in the pre-review candidate manifest
- **THEN** the system SHALL record the review diagnostic as `REVIEW_ENVIRONMENT_INVALID`, reject the review findings from blocking the candidate, and prevent progression to audit or human merge until reviewer visibility is reconciled.

### Requirement: Machine-readable evidence diagnostic model
The system SHALL record check and review execution diagnostics using a machine-readable diagnostic enum: `PASS`, `FAIL`, `SKIPPED_BY_POLICY`, `ENVIRONMENT_UNAVAILABLE`, `EVIDENCE_NOT_REPRODUCIBLE`, or `REVIEW_ENVIRONMENT_INVALID`. These diagnostics represent evidence/environment execution quality and SHALL NOT be treated as canonical job statuses.

#### Scenario: Integration test unable to reach local daemon database
- **WHEN** an integration check cannot execute because the reviewer or test environment lacks PostgreSQL daemon connectivity or credentials
- **THEN** the system SHALL record the check diagnostic as `ENVIRONMENT_UNAVAILABLE` with reason details, rather than recording a `FAIL` verdict.

#### Scenario: Authoritative check execution in canonical project environment
- **WHEN** a check diagnostic is `ENVIRONMENT_UNAVAILABLE` in a restricted agent environment but produces `PASS` when executed in the canonical project host environment
- **THEN** the canonical project environment check result SHALL be accepted as authoritative evidence for completion verification.
