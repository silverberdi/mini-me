## Purpose
Manage the two-phase pull request delivery cycle, complexity-differentiated merge policies, fresh documentation worktree setup, native OpenSpec Sync and Archive execution, second PR auto-merge, remote issue closure, and continuous transition to the next eligible Request.

## ADDED Requirements

### Requirement: Implementation Pull Request Creation
Upon receiving `READY FOR PR` from the implementation stage, the system SHALL push the request branch to the remote repository, SHALL open a Pull Request targeting the configured base branch (`main`), SHALL bind the PR to the exact verified candidate commit SHA, and SHALL confirm remote branch protections and permissions.

#### Scenario: Implementation PR opened from request branch
- **WHEN** the implementation and verification (and code review if high complexity) succeed
- **THEN** mini me opens the implementation PR, includes the summary of change and test evidence in the description, and records the PR number and URL.

### Requirement: Merge Policy for Implementation PR
The system SHALL apply a differentiated merge policy for the implementation PR based on the complexity assessed during Propose: for low or moderate complexity, mini me SHALL merge the PR automatically; for high complexity, mini me SHALL emit `HUMAN REQUIRED` exclusively for an informational acknowledgement («Estoy enterado») with a plain Spanish summary before merging.

#### Scenario: Low or moderate complexity PR merges automatically
- **WHEN** the implementation PR is opened for a change of low or moderate complexity
- **AND** remote checks and branch protections are satisfied
- **THEN** mini me automatically merges the PR into `main` without human intervention.

#### Scenario: High complexity PR requires human informational acknowledgement
- **WHEN** the implementation PR is opened for a change of high complexity
- **THEN** mini me pauses with `HUMAN REQUIRED`, presents a concise, clear summary in Spanish, and upon the operator submitting «Estoy enterado», immediately proceeds to execute the merge.

#### Scenario: Remote branch protections are strictly respected
- **WHEN** an automated or acknowledged merge is attempted but GitHub branch protections (required reviews, CI checks) are unmet
- **THEN** the merge fails closed, preserving the exact remote error reason without attempting to bypass protections.

### Requirement: Fresh Worktree Setup for Documentation Closure
Following remote confirmation that the implementation PR is merged into `main`, the system SHALL update the remote reference of `main`, SHALL create a fresh documentation branch (`doc-close-<numero>-<slug-kebab>`) and worktree rooted at the merged `main` commit, and SHALL NOT reuse the dirty implementation worktree.

#### Scenario: Documentation branch and worktree rooted on merged main
- **WHEN** the first PR merge is confirmed on GitHub
- **THEN** mini me creates `doc-close-<numero>-<slug-kebab>` from updated `main` and prepares an isolated worktree for documentation operations.

### Requirement: Native OpenSpec Sync and Archive Execution
The system SHALL dispatch the thinking agent configured with lowest compatible effort to execute the official OpenSpec Sync workflow followed by the official OpenSpec Archive workflow, SHALL commit and push the resulting documentation changes, and SHALL NOT emulate Sync or Archive via custom Markdown scripts or manual directory moves.

#### Scenario: Thinking agent executes native sync and archive
- **WHEN** the documentation worktree is ready
- **THEN** the thinking agent executes official OpenSpec Sync, updates main specs from deltas, executes official OpenSpec Archive, moves the change to archive, commits the files, pushes the branch, and emits `READY FOR PR`.

### Requirement: Documentation Pull Request and Auto-Merge
The system SHALL open a second Pull Request from the documentation branch to `main`, SHALL verify that it contains exclusively documentation and OpenSpec updates, and SHALL automatically merge it regardless of the original change's complexity.

#### Scenario: Second PR auto-merges unconditionally
- **WHEN** the documentation PR is opened
- **THEN** mini me automatically merges the second PR into `main`, confirming remote merge completion.

### Requirement: Remote Issue Closure and FIFO Continuation
Only after remote confirmation that the second documentation PR is merged into `main`, the system SHALL close the remote GitHub Issue, record idempotent completion in PostgreSQL, release the active project lock, and immediately invoke request selection for the next eligible FIFO Request.

#### Scenario: Remote issue closed and next ticket selected
- **WHEN** the second PR merge is confirmed on GitHub
- **THEN** mini me closes the GitHub issue with a concise completion comment, clears the active request binding, and automatically queries the next oldest eligible issue to continue the loop.
