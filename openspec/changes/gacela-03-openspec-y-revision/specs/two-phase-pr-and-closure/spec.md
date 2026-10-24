## Purpose
Manage the two-phase pull request delivery cycle, complexity-differentiated merge policies, fresh documentation worktree setup, native OpenSpec Sync and Archive execution, second PR auto-merge, remote issue closure, and continuous transition to the next eligible Request.

## ADDED Requirements

### Requirement: Implementation Pull Request Preparation via Minimal Skill Delivered in F3
The system SHALL deliver the minimal PR preparation skill (`minime-pr-preparer`) within F3 and SHALL invoke it to generate the structured title and Markdown description for the implementation PR without depending on F4 capabilities. The skill contract SHALL accept structured input (project, repository, `pr_type: implementation`, original request details, base branch, candidate branch, candidate commit SHA, change summary, test/verify evidence, and OpenSpec change name) and SHALL return structured output (formatted title, structured description with test evidence and `Fixes #...`, and metadata). The system SHALL use `GitHubAdapter` to push the branch, open the Pull Request, bind it to the verified candidate SHA, and check remote protections. Agent guardian directives (`minime-git-workspace-guardian`, `minime-github-work-management-guardian`) SHALL apply strictly to autonomous agent git operations in the worktree, whereas the remote merge SHALL be executed exclusively by mini me coordinator via `GitHubAdapter`.

#### Scenario: Implementation PR prepared via minimal skill and opened
- **WHEN** the implementation and verification (and code review if high complexity) succeed
- **THEN** mini me invokes the minimal PR preparation skill in the agent runner, receives the structured PR content, opens the implementation PR via `GitHubAdapter` bound to the verified candidate SHA, and records the PR number and URL.

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
Following remote confirmation that the implementation PR is merged into `main`, the system SHALL update the remote reference of `main`, SHALL create a fresh documentation branch (`doc-close-<numero>-<slug-kebab>`) and worktree rooted at the merged `main` commit under the project's configured managed root, and SHALL NOT reuse the dirty implementation worktree.

#### Scenario: Documentation branch and worktree rooted on merged main
- **WHEN** the first PR merge is confirmed on GitHub
- **THEN** mini me creates `doc-close-<numero>-<slug-kebab>` from updated `main` and prepares an isolated worktree under the resolved managed root for documentation operations.

### Requirement: Native OpenSpec Sync and Archive Execution
The system SHALL dynamically resolve the official OpenSpec Sync and Archive workflows for the thinking agent based on the workflows installed in the documentation worktree (`.agent/workflows/opsx-sync.md` and `opsx-archive.md` for Antigravity vs `.agents/skills/openspec-sync-specs/SKILL.md` and `openspec-archive-change/SKILL.md` for Codex) and provider prompt transport. The system SHALL dispatch the thinking agent configured with lowest compatible effort to execute the resolved Sync workflow followed by Archive, SHALL commit and push the resulting documentation changes, and SHALL NOT emulate Sync or Archive via custom Markdown scripts or manual directory moves.

#### Scenario: Thinking agent executes native sync and archive
- **WHEN** the documentation worktree is ready
- **THEN** the thinking agent executes the resolved official OpenSpec Sync, updates main specs from deltas, executes resolved official OpenSpec Archive, moves the change to archive, commits the files, pushes the branch, and emits `READY FOR PR`.

### Requirement: Documentation Pull Request via Minimal Skill and Auto-Merge
The system SHALL invoke the minimal PR preparation skill (`minime-pr-preparer`) with `pr_type: documentation` for the documentation branch, SHALL open a second Pull Request from the documentation branch to `main` via `GitHubAdapter`, SHALL verify that it contains exclusively documentation and OpenSpec updates, and SHALL automatically merge it regardless of the original change's complexity.

#### Scenario: Second PR auto-merges unconditionally
- **WHEN** the documentation PR is opened via the minimal PR preparation skill
- **THEN** mini me automatically merges the second PR into `main`, confirming remote merge completion.

### Requirement: Remote Issue Closure, FIFO Continuation, and Test Isolation
Only after remote confirmation that the second documentation PR is merged into `main`, the system SHALL close the remote GitHub Issue, record idempotent completion in PostgreSQL, release the active project lock, and immediately invoke request selection for the next eligible FIFO Request. All E2E automated tests exercising PR creation, merge, and issue closure SHALL execute exclusively against an authorized, isolated test repository without mutating the operational mini me repository or issues.

#### Scenario: Remote issue closed and next ticket selected
- **WHEN** the second PR merge is confirmed on GitHub
- **THEN** mini me closes the GitHub issue with a concise completion comment, clears the active request binding, and automatically queries the next oldest eligible issue to continue the loop.

#### Scenario: End-to-end pull request and closure tests run in isolated repository
- **WHEN** end-to-end integration tests execute the two-phase PR and closure workflow
- **THEN** the tests target an isolated test repository (e.g. `mini-me-fixture`) and never mutate `silverberdi/mini-me` or its operational issues.
