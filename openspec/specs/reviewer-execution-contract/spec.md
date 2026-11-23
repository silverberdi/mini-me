# Reviewer Execution Contract Specification

## Purpose

Defines a provider-neutral reviewer execution contract providing immutable change identity, candidate SHA, base SHA, worktree context, and check evidence to the complementary reviewer agent.

## Requirements

### Requirement: Explicit change identity and SHA propagation
The system SHALL invoke the complementary reviewer with explicit immutable execution identity, including `project_id`, exact `change_id`, candidate HEAD SHA, base SHA, candidate worktree path, OpenSpec artifact locations, and deterministic check evidence.

#### Scenario: Reviewer receives explicit change identity and candidate SHA
- **WHEN** a review execution is launched for a candidate
- **THEN** the reviewer execution payload contains the exact change ID, candidate SHA, base SHA, worktree directory, and preceding check results
- **AND** the system SHALL NOT allow the reviewer to infer or select an active or newest change implicitly.

### Requirement: Reviewer process execution with timeout and redaction
The system SHALL execute the complementary reviewer CLI/subprocess inside the candidate worktree with process group isolation, execution timeout enforcement, and secret redaction on all captured output streams. The reviewer invocation SHALL be proven read-only and non-interactive (no human approval interaction) and SHALL NOT mutate the candidate worktree.

#### Scenario: Reviewer process completes within timeout
- **WHEN** the reviewer process executes and exits within the configured timeout
- **THEN** stdout and stderr are captured, redacted of all sensitive patterns, and stored in the review log stream.

#### Scenario: Reviewer process exceeds timeout
- **WHEN** the reviewer process runs longer than the configured timeout duration
- **THEN** the system SHALL terminate the subprocess group (SIGTERM followed by SIGKILL), transition the review status to `REVIEW_TIMED_OUT`, and record a `REVIEW_TIMEOUT` event.

#### Scenario: Reviewer runs read-only without human approval interaction
- **WHEN** the configured reviewer invocation is executed
- **THEN** it SHALL run read-only and SHALL NOT require interactive human approval.

#### Scenario: Reviewer remains non-mutating
- **WHEN** the reviewer process completes
- **THEN** the candidate worktree SHALL remain unmodified (no new files, commits, or task checkbox changes) by the reviewer.

### Requirement: Verdict-first prompt formatting and diff hygiene
The system SHALL compose reviewer prompts that request the structured review verdict JSON as the first output line. Review input SHALL exclude dependency lockfiles, binary payloads, `src/*/static/**`, `frontend/dist/**`, source maps, and minified JavaScript; sources such as `frontend/src/**` SHALL remain represented. Large inputs SHALL use the configured prompt transport rather than placing an unbounded payload in process arguments. If provider context limits still require partitioning, the system SHALL preserve coverage of every review-relevant changed file and clearly identify the portions supplied to the reviewer; it SHALL NOT silently truncate the diff or claim complete review when relevant changes were omitted. Diff base SHALL resolve from the verified remote tracking base commit (`merge-base`), not an unsynchronized local branch reference.

#### Scenario: Review prompt mandates JSON verdict first
- **WHEN** the orchestrator builds the prompt for independent proposal or code review
- **THEN** it instructs the reviewer to emit one structured JSON verdict object as its first output line before narrative remarks.

#### Scenario: Code review diff excludes non-code lockfiles
- **GIVEN** a candidate diff includes dependency lockfiles, binary payloads, files under `src/*/static/**` or `frontend/dist/**`, source maps, and minified JavaScript alongside authored frontend source
- **WHEN** the reviewer input is prepared
- **THEN** the build output and non-reviewable payloads are excluded or represented with concise metadata and provenance
- **AND** authored source under `frontend/src/**` remains included or otherwise explicitly covered by the review evidence.

#### Scenario: Large reviewer input respects transport and context limits
- **GIVEN** a candidate reviewer input exceeds the configured safe size for direct process arguments or a single provider context
- **WHEN** mini me prepares the review invocation
- **THEN** it uses the configured non-argument prompt transport and, if necessary, partitions the relevant changed-file evidence without silently dropping files
- **AND** it reports a concrete transport or provider limit if full relevant coverage cannot be achieved.

#### Scenario: Code review diff resolves against remote merge base
- **WHEN** the orchestrator determines the base ancestor for the review diff
- **THEN** it resolves the diff against the verified remote tracking base commit using `merge-base`, not a potentially unsynchronized local branch reference.

### Requirement: Reviewer findings are grounded in observable test evidence
The complementary reviewer SHALL evaluate test and database-isolation claims using the exact candidate SHA, repository configuration, executed commands, redacted results, and any matching project CI checks. Narrative disclaimers or agent assertions alone SHALL NOT establish that a test was run, passed, failed, or is impossible; the reviewer SHALL identify a concrete contradiction or missing observable evidence before treating a test claim as a blocking finding. Pending deferred checks SHALL remain pending until conclusive same-SHA CI evidence exists.

#### Scenario: Reviewer accepts observable test evidence over a generic disclaimer
- **GIVEN** the candidate SHA has an observable successful configured test result or matching CI check
- **AND** a narrative disclaimer claims without contrary evidence that the test remains unverified
- **WHEN** the complementary reviewer evaluates the candidate
- **THEN** it uses the observable result and does not block solely on the disclaimer
- **AND** it cites the command or CI check and candidate SHA supporting its conclusion.

#### Scenario: Reviewer rejects unsubstantiated test completion
- **GIVEN** an agent or proposal claims a test passed but no matching command or CI result is observable for the candidate SHA
- **WHEN** the complementary reviewer evaluates the candidate
- **THEN** it does not accept the claim as evidence
- **AND** it identifies the missing command, result, or SHA binding as the specific finding.

#### Scenario: Deferred test is not misreported as complete
- **GIVEN** a required test has an authorized PR CI path but its same-SHA check is pending or unavailable
- **WHEN** the complementary reviewer evaluates the candidate
- **THEN** it reports the test as pending for that check
- **AND** it neither marks it complete nor blocks solely because it is scheduled for that later stage.
