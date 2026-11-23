## MODIFIED Requirements

### Requirement: Merge Policy for Implementation PR
The system SHALL apply the differentiated implementation PR merge policy based on complexity: for low or moderate complexity, mini me SHALL merge automatically; for high complexity, mini me SHALL require the informational «Estoy enterado» acknowledgement with a plain Spanish summary before attempting the merge. All merges SHALL respect GitHub branch protections and required checks. If GitHub returns HTTP 405, mini me SHALL read back the pull request's current mergeability state and retry only while GitHub reports mergeability as unknown/transient, using a bounded backoff. A confirmed conflict, policy restriction, failed check, or other permanent rejection SHALL remain a typed fail-closed outcome; retries SHALL NOT bypass or override it.

#### Scenario: Low or moderate complexity PR merges automatically
- **GIVEN** PR1 is open for a low or moderate complexity change
- **AND** remote checks, reviews, and branch protections are satisfied
- **WHEN** the coordinator invokes the GitHub merge operation
- **THEN** GitHub returns the merge commit SHA and mini me records it before advancing to documentation worktree setup.

#### Scenario: High complexity PR requires human informational acknowledgement
- **GIVEN** PR1 for a high complexity change is ready to merge
- **WHEN** the change reaches the merge stage
- **THEN** mini me presents a concise Spanish summary and waits for «Estoy enterado»
- **AND** only after that acknowledgement does it attempt the merge.

#### Scenario: HTTP 405 with unknown mergeability is retried within a bound
- **GIVEN** a merge attempt returns HTTP 405
- **AND** an authoritative PR read-back reports mergeability as unknown/transient rather than conflict or policy denial
- **WHEN** the configured bounded backoff permits another attempt
- **THEN** mini me retries the same PR merge and records the response and read-back evidence
- **AND** it stops retrying when the bound is reached.

#### Scenario: Permanent merge rejection remains fail-closed
- **GIVEN** a merge attempt returns HTTP 405 or another merge rejection
- **AND** PR read-back or GitHub's typed response confirms a branch-protection restriction, conflict, failed check, or other permanent denial
- **WHEN** the coordinator handles the result
- **THEN** it records a typed failure and preserves the PR and worktree
- **AND** it does not retry past policy or override GitHub protections.

#### Scenario: Remote branch protections are strictly respected
- **GIVEN** an automated or acknowledged merge attempt on GitHub
- **WHEN** required reviews, checks, or status contexts are missing or failing
- **THEN** the GitHub adapter returns a typed merge error
- **AND** mini me halts fail-closed, preserving PR state and worktree without attempting unauthorized overrides.
