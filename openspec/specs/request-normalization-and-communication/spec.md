## Purpose

Provide one small, traceable contract for turning a remote Request into usable Gherkin and communicating delivery progress without duplicating GitHub or F3 orchestration.

## Requirements

### Requirement: Request normalization preserves source authority

The system SHALL normalize an eligible GitHub Request into complete valid Gherkin before invoking OpenSpec Explore, reusing the same Run, authorized Worktree, continuity checkpoint, and configured thinking agent. It SHALL update the same Issue while preserving the complete original body literally in a comment on that Issue, together with comments, attachments, all identified acceptance criteria, and stable criterion identifiers. An Issue already expressed as complete precise Gherkin SHALL continue without semantic rewrite.

#### Scenario: Informal Request becomes a vertical slice

- **WHEN** an eligible Issue contains informal requirements and its sources are available
- **THEN** the normalized body SHALL fully express one vertical slice with observable Given, When, and Then scenarios
- **AND** the complete original body SHALL be preserved verbatim in a comment on the same Issue
- **AND** every identified acceptance criterion SHALL remain represented and traceable
- **AND** Explore SHALL receive the normalized Request only after source-preservation and remote-version postconditions pass

#### Scenario: Existing Gherkin is preserved

- **WHEN** the Issue body is already complete and precise Gherkin
- **THEN** the system SHALL preserve its meaning without duplicating criteria or comments
- **AND** it SHALL still preserve the complete source body according to the Request provenance contract
- **AND** the existing Run SHALL continue to Explore without rewriting the Issue body

#### Scenario: Material ambiguity remains explicit

- **WHEN** authoritative sources do not resolve a material business decision
- **THEN** the system SHALL preserve the uncertainty and use the existing concrete HUMAN REQUIRED path only for the unresolved material decision
- **AND** it SHALL NOT invent requirements, endpoints, tables, frameworks, or approvals
- **AND** technical failures, missing capabilities, authentication, quota, or security issues SHALL follow their technical preflight and recovery paths rather than HUMAN REQUIRED

#### Scenario: Controlled test Issue protects the F4 Request

- **WHEN** S01 is verified during F4
- **THEN** it SHALL use a controlled disposable test Issue and SHALL NOT rewrite the already normalized Issue #172
- **AND** any legitimate F3 closure communication for Issue #172 SHALL remain governed by F3

#### Scenario: Concurrent normalization is safe

- **WHEN** a retry or remote concurrent edit occurs before publishing normalization
- **THEN** the system SHALL re-read the remote Issue, avoid overwriting unrelated changes, and avoid duplicate comments
- **AND** it SHALL verify the resulting remote version before continuing

#### Scenario: Original body is preserved through the GitHub adapter

- **WHEN** the agent-produced normalization is ready to publish
- **THEN** `GitHubAdapter` SHALL re-read the Issue version before updating its body
- **AND** SHALL create or reconcile one idempotent provenance comment containing the original body literally
- **AND** SHALL confirm the updated body and comment remotely before Explore starts
- **AND** SHALL leave the candidate and checkpoint intact if the version or postcondition cannot be confirmed

### Requirement: Delivery communication is concise Spanish

The agent skill SHALL produce the semantic content of value-adding comments in simple Spanish for material blockers, questions, milestones, results, and final closure. The existing GitHub adapter SHALL only query and publish that content deterministically, safely, and idempotently, avoiding secrets, long logs, and repeated messages.

#### Scenario: Material event gets a useful comment

- **WHEN** a blocker, question, relevant result, or milestone needs remote communication
- **THEN** the comment SHALL state what happened, the result, and the required action in concrete Spanish
- **AND** the GitHub adapter SHALL publish it idempotently without generating semantic text by template

#### Scenario: Closure follows F3 evidence

- **WHEN** F3 confirms both PR merges and native Sync and Archive have completed
- **THEN** the system SHALL publish one concise Spanish closure comment with verifiable links
- **AND** a retry SHALL not duplicate the comment or close the Issue twice
- **AND** technical failures SHALL not be escalated as human decisions

### Requirement: PR preparation remains under F3 authority

The system SHALL prepare implementation and documentary PR content from verified evidence while leaving branch protection, merge decisions, candidate identity, and lifecycle orchestration to the existing GitHub adapter and F3 coordinator.

#### Scenario: Implementation PR is prepared

- **WHEN** F3 provides READY FOR PR for an implementation candidate
- **THEN** the PR content SHALL link the Request and Change, summarize covered criteria, real tests, evidence, and known restrictions without inventing results

#### Scenario: Documentary PR is prepared

- **WHEN** the first PR is merged and native Sync and Archive finish on a fresh closure branch
- **THEN** the documentary PR SHALL identify the implementation PR, synchronized documentation, and evidence while retaining F3 merge rules
- **AND** `PrPreparerService` SHALL obtain the semantic title/body from `minime-pr-preparer` using the Request and evidence, while code validates repository, base/head SHA, non-closing references, and remote identity before publication
