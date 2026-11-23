## MODIFIED Requirements

### Requirement: Verdict-first prompt formatting and diff hygiene
The system SHALL compose reviewer prompts that request the structured review verdict JSON as the first output line. Review input SHALL exclude dependency lockfiles, binary payloads, `src/*/static/**`, `frontend/dist/**`, source maps, and minified JavaScript; sources such as `frontend/src/**` SHALL remain represented. Large inputs SHALL use the configured prompt transport rather than placing an unbounded payload in process arguments. If provider context limits still require partitioning, the system SHALL preserve coverage of every review-relevant changed file and clearly identify the portions supplied to the reviewer; it SHALL NOT silently truncate the diff or claim complete review when relevant changes were omitted. Diff base SHALL resolve from the verified remote tracking base commit (`merge-base`), not an unsynchronized local branch reference.

#### Scenario: Review prompt mandates JSON verdict first
- **WHEN** the orchestrator builds a prompt for independent proposal or code review
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
