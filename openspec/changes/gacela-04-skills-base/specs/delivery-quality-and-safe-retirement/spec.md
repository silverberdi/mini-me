## Purpose

Give F4 a proportional quality and retirement contract that proves functional value with real tests while keeping OpenSpec, provider policy, and production boundaries owned by their existing components.

## ADDED Requirements

### Requirement: Engineering guidance is contextual and bounded

The adapted `minime-engineering-discipline` skill in both Codex and Antigravity installations SHALL guide agents toward readable, cohesive code and the approved project architecture using existing context, without imposing universal layers, patterns, line limits, frameworks, or a second OpenSpec authority.

#### Scenario: Existing architecture is respected

- **WHEN** an agent implements application code within a Change
- **THEN** the guidance SHALL distinguish current decisions from historical documents and SHALL reuse the project's stack and conventions
- **AND** it SHALL not require editing OpenSpec artifacts as a quality gate or alter OpenSpec artifact generation, validation, Verify, or independent review

#### Scenario: Guidance does not become a gate

- **WHEN** a hook or harness provides engineering assistance
- **THEN** it SHALL facilitate investigation and work without becoming a new approval gate or parallel semantic validator

### Requirement: Quality evidence demonstrates functional value

The adapted `minime-real-e2e-proof` skill in both Codex and Antigravity installations SHALL require proportional unit, integration, negative, regression, and automated E2E evidence according to the delivered behavior and project ecosystem, and SHALL distinguish real E2E from mocks without requiring deployment or postdeploy verification in F4.

#### Scenario: Real project behavior is proven

- **WHEN** a Request Change is implemented and tested
- **THEN** at least one automated E2E test SHALL exercise the real appropriate project interface and relevant acceptance criteria
- **AND** the recorded result SHALL come from an executed test rather than an assertion of success
- **AND** an unauthorized or unavailable real-agent run SHALL be recorded as `NOT_VERIFIED` or `WAITING_CAPACITY`, never PASS

#### Scenario: Test scope follows the project

- **WHEN** the project is a web, mobile, console, API, or library project
- **THEN** the test guidance SHALL use its existing tools and shall not require an unrelated browser, deployment, provider, or stack

### Requirement: Superseded code is retired safely

The adapted `minime-safe-retirement` skill in both Codex and Antigravity installations SHALL retire only routes, tests, dependencies, configuration, or data structures demonstrated to be obsolete within the Change after migrating real consumers and running pertinent tests. It SHALL use proportional evidence and SHALL NOT impose a universal Removal Ledger, postdeploy verification, or R01–R10 procedure.

#### Scenario: Obsolete route has no consumers

- **WHEN** static, dynamic, and configuration consumers demonstrate that a replaced route is orphaned
- **THEN** the Change SHALL remove the orphaned implementation and relevant tests/configuration and SHALL execute the affected regression tests
- **AND** it SHALL record concise consumer evidence rather than a mandatory universal ledger

#### Scenario: Historical or active consumer remains

- **WHEN** a candidate route or data structure still has a legitimate consumer or historical compatibility obligation
- **THEN** the Change SHALL preserve it and record the reason briefly
- **AND** it SHALL not remove it solely because it is old or textually unmatched
- **AND** historical R01–R10 references SHALL not justify removal without current consumer evidence

