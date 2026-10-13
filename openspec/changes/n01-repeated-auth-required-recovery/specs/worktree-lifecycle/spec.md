## Purpose

Specify safe reuse of an existing CREATED execution worktree following repeated authentication failures when a fresh human-authorized continuation can be proven.

## ADDED Requirements

### Requirement: Repeated AUTH_REQUIRED recovery of an existing CREATED worktree

The system SHALL permit reuse of an existing CREATED worktree after a finite AUTH_REQUIRED/no-progress attempt chain only when durable evidence is complete, consistent, and bound to a fresh canonical human continuation. This exception SHALL NOT change automatic retry policy or authorize DELETED worktree recreation.

#### Scenario: Repeated same-SHA authentication suppressions followed by authorized continuation

- **WHEN** a CREATED worktree has a contiguous, uniquely identified attempt history anchored by a provider or provider-preflight failure, and every repeated duplicate is AUTH_REQUIRED / SAME_SHA_NO_PROGRESS with unchanged non-empty start/end SHA and exactly one matching durable suppression event
- **AND** a fresh CONTROL_PLANE DRIVE_CONTINUATION decision for the same Run, project, and change is executing under its active CAS-valid fence after the latest attempt
- **AND** ownership, candidate absence, snapshot, branch, remote identity, publication, and Git integrity checks pass
- **THEN** the system SHALL reuse the same worktree without rewriting prior attempts, changing retry policy, or creating another Run or Job.

#### Scenario: Contradictory or incomplete suppression chain

- **WHEN** any attempt, SHA, classification, timestamp, identity, or suppression event is missing, duplicated, extra, contradictory, or cannot be fully observed
- **THEN** the system SHALL fail closed and SHALL NOT reuse the worktree.

#### Scenario: Automatic retry or deleted worktree

- **WHEN** reuse is requested without a fresh human-authorized CONTROL_PLANE continuation, or ownership is DELETED / the physical worktree is absent
- **THEN** the repeated-authentication exception SHALL NOT authorize reuse or recreation.
