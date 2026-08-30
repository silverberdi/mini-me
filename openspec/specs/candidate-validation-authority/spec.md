# Candidate Validation Authority Specification

## Purpose

Binds human and automated visual validation authority strictly to immutable candidate tuples `(head_sha, base_sha, image_digest)`, enforces strict stale invalidation upon any mutation to candidate inputs or base ancestry, preserves historical validation audit trails, and gates delivery pipeline merge readiness.

## Requirements

### Requirement: Candidate Identity Authority Binding
The system SHALL bind every validation run strictly to the exact tuple `(head_sha, base_sha, image_digest)`.

#### Scenario: Valid candidate validation record
Given a frozen candidate with head SHA `sha_h1`, base SHA `sha_b1`, and image digest `sha256:img1`
When an operator completes a validation run with verdict `PASS`
Then the validation record SHALL store `head_sha=sha_h1`, `base_sha=sha_b1`, and `image_digest=sha256:img1`
And the validation SHALL be evaluated as valid for that candidate tuple.

### Requirement: Strict Stale Validation Invalidation
The system SHALL evaluate any prior validation as stale and non-authorizing whenever the candidate head SHA, base SHA, or image digest changes.

#### Scenario: Head SHA drift invalidation
Given a previous candidate generation with head SHA `sha_h1` that received a `PASS` validation
When code remediation or updates produce a new candidate with head SHA `sha_h2`
Then the previous validation SHALL be marked as stale
And the new candidate `sha_h2` SHALL NOT be authorized until a new validation run is recorded.

#### Scenario: Base SHA drift invalidation
Given a candidate with head SHA `sha_h1` and base SHA `sha_b1` that received a `PASS` validation
When base branch integration updates the base SHA to `sha_b2`
Then the validation for `(sha_h1, sha_b1)` SHALL be marked as stale
And candidate authority SHALL NOT authorize merge without a fresh validation.

#### Scenario: Historical evidence preservation
Given a candidate update that invalidates a prior validation
When validation history is queried
Then the prior validation SHALL remain persisted in the database as historical audit evidence with `is_stale=True`.

### Requirement: Delivery Pipeline Validation Gate
The system SHALL block pull request finalization and human merge authorization for UI-affecting changes until an active, non-stale `PASS` validation exists.

#### Scenario: Blocking unvalidated UI candidate
Given a change requiring UI validation that has passed checks, review, and audit
When the orchestration pipeline attempts to advance to `PR_PREPARED` or `READY_FOR_HUMAN_MERGE`
And no valid non-stale `PASS` validation exists for the candidate tuple
Then the pipeline SHALL stop at the validation gate with `NEEDS_HUMAN`
And the pipeline SHALL NOT mark the candidate ready for merge.

#### Scenario: Authorizing validated UI candidate
Given a change requiring UI validation
And a valid non-stale `PASS` validation exists for the candidate's exact `(head_sha, base_sha, image_digest)`
When the orchestration pipeline evaluates the candidate gate
Then the validation gate SHALL pass and allow the candidate to transition to `PR_PREPARED` / `READY_FOR_HUMAN_MERGE`.
