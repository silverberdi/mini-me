## Purpose

Provide one small, traceable contract for turning a remote Request into usable Gherkin and communicating delivery progress without duplicating GitHub or F3 orchestration.

## ADDED Requirements

### Requirement: Request normalization preserves source authority

The system SHALL normalize an eligible GitHub Request into valid Gherkin on the same Issue while preserving the complete original body, comments, attachments, acceptance criteria, and stable criterion identifiers.

#### Scenario: Informal Request becomes a vertical slice

- **WHEN** an eligible Issue contains informal requirements and its sources are available
- **THEN** the normalized body SHALL describe one vertical slice with observable Given, When, and Then scenarios
- **AND** the original text SHALL remain traceable in a comment or preserved source reference

#### Scenario: Existing Gherkin is preserved

- **WHEN** the Issue body is already complete and precise Gherkin
- **THEN** the system SHALL preserve its meaning without duplicating criteria or comments

#### Scenario: Material ambiguity remains explicit

- **WHEN** authoritative sources do not resolve a material business decision
- **THEN** the system SHALL preserve the uncertainty and emit the existing concrete HUMAN REQUIRED path
- **AND** it SHALL NOT invent requirements, endpoints, tables, frameworks, or approvals

#### Scenario: Concurrent normalization is safe

- **WHEN** a retry or remote concurrent edit occurs before publishing normalization
- **THEN** the system SHALL re-read the remote Issue, avoid overwriting unrelated changes, and avoid duplicate comments
- **AND** it SHALL verify the resulting remote version before continuing

### Requirement: Delivery communication is concise Spanish

The system SHALL prepare only value-adding comments in simple Spanish for material blockers, questions, milestones, results, and final closure, using GitHub as the remote authority and avoiding secrets, long logs, and repeated messages.

#### Scenario: Material event gets a useful comment

- **WHEN** a blocker, question, relevant result, or milestone needs remote communication
- **THEN** the comment SHALL state what happened, the result, and the required action in concrete Spanish
- **AND** the GitHub adapter SHALL publish it idempotently

#### Scenario: Closure follows F3 evidence

- **WHEN** F3 confirms both PR merges and native Sync and Archive have completed
- **THEN** the system SHALL publish one concise Spanish closure comment with verifiable links
- **AND** a retry SHALL not duplicate the comment or close the Issue twice

### Requirement: PR preparation remains under F3 authority

The system SHALL prepare implementation and documentary PR content from verified evidence while leaving branch protection, merge decisions, candidate identity, and lifecycle orchestration to the existing GitHub adapter and F3 coordinator.

#### Scenario: Implementation PR is prepared

- **WHEN** F3 provides READY FOR PR for an implementation candidate
- **THEN** the PR content SHALL link the Request and Change, summarize covered criteria, real tests, evidence, and known restrictions without inventing results

#### Scenario: Documentary PR is prepared

- **WHEN** the first PR is merged and native Sync and Archive finish on a fresh closure branch
- **THEN** the documentary PR SHALL identify the implementation PR, synchronized documentation, and evidence while retaining F3 merge rules

