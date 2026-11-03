## MODIFIED Requirements

### Requirement: Independent Implementation Code Review for High Complexity
For high-complexity changes, the configured independent reviewer agent SHALL receive a read-only prompt containing the Request, approved proposal, specifications, code, the complete candidate diff without truncation, and test evidence. The reviewer SHALL NOT modify code or execute OpenSpec workflows, and SHALL evaluate requirement fulfillment, functional correctness, security, and scope. The review prompt SHALL require findings to use these severities: BLOCKER means the change cannot be implemented safely; MAJOR means a real correctness or security gap; MINOR means a non-blocking nit. The reviewer SHALL focus on new, material defects, SHALL NOT re-flag requirements already covered, and SHALL NOT request wording or formatting changes.

#### Scenario: Independent reviewer approves implementation with structured verdict
- **GIVEN** a high-complexity change in `READY FOR INDEPENDENT REVIEW`
- **AND** a distinct read-only reviewer agent configured in project settings
- **WHEN** mini me dispatches the reviewer agent with diff, specs, and test execution evidence
- **THEN** the reviewer evaluates the code without write permissions or branch modifications
- **AND** emits an APPROVED verdict with written justification
- **AND** the coordinator records the review result in PostgreSQL and advances to `READY FOR PR`.

#### Scenario: Independent reviewer rejects with actionable findings
- **GIVEN** a high-complexity change under independent review
- **WHEN** the reviewer detects missing requirements, architectural defects, security issues, or regressions
- **THEN** the reviewer emits a CHANGES REQUESTED verdict with specific, actionable findings
- **AND** mini me routes the change back to the implementer agent via Apply correction prompt
- **AND** requires green test execution and OpenSpec Verify re-check before re-submitting to the reviewer.

#### Scenario: Reviewer receives the complete candidate diff
- **GIVEN** a high-complexity candidate whose diff exceeds 4,000 characters
- **WHEN** the independent code review prompt is prepared
- **THEN** the prompt includes the complete candidate diff without truncation.

#### Scenario: Code review findings converge on substantive defects
- **GIVEN** a high-complexity candidate under independent code review
- **WHEN** the reviewer evaluates its requirements, implementation, and complete diff
- **THEN** it reports only new, material correctness, security, or scope defects
- **AND** assigns BLOCKER, MAJOR, or non-blocking MINOR according to the stated severity definitions
- **AND** does not re-flag requirements already covered or request wording or formatting changes.
