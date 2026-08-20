# Candidate Integrity Verification Specification

## Purpose

Ensures candidate workspace, commit SHA, and check evidence integrity before review, and enforces read-only non-mutation boundaries during reviewer execution.

## Requirements

### Requirement: Pre-review candidate and evidence integrity validation
The system SHALL verify that the candidate worktree HEAD SHA matches the SHA recorded upon implementer completion, that the base SHA matches the registered project base branch, and that deterministic checks successfully ran against that exact candidate SHA.

#### Scenario: Stale or mutated candidate detected pre-review
- **WHEN** the HEAD SHA of the candidate worktree does not match the candidate SHA recorded on the job record
- **THEN** the system SHALL block review invocation, transition the job to `FAILED`, and record a `CANDIDATE_SHA_MISMATCH` event.

### Requirement: Read-only reviewer authority boundary enforcement
The system SHALL verify that the complementary reviewer process did not create new commits, alter candidate worktree files, or modify OpenSpec task checkbox states.

#### Scenario: Post-review candidate non-mutation check passes
- **WHEN** the reviewer process completes
- **THEN** the system SHALL verify `git status --porcelain` in the worktree is clean and `git rev-parse HEAD` is identical to the candidate SHA
- **AND** if uncommitted changes or new commits are detected, the system SHALL reject the review outcome, mark the review as `REVIEW_FAILED`, and record an `UNAUTHORIZED_REVIEWER_MUTATION` event.
