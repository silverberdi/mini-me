## MODIFIED Requirements

### Requirement: Fail-closed completion verification
The system SHALL independently verify implementation completion claims by inspecting OpenSpec task checkbox state, worktree git status, presence of required candidate artifacts, deterministic check exit codes, and candidate commit SHA before advancing a job to the review phase.

#### Scenario: Executor claims completion with pending OpenSpec tasks
- **WHEN** an executor reports completion but `openspec/changes/<change_id>/tasks.md` contains uncompleted checkboxes
- **THEN** completion verification SHALL fail closed, classify the outcome as `PREMATURE_STOP` or `EVIDENCE_INSUFFICIENT`, and block transition to review.

#### Scenario: Executor claims completion with failing deterministic checks
- **WHEN** an executor claims completion but one or more configured deterministic checks exit with non-zero status
- **THEN** completion verification SHALL fail closed, classify the outcome as `CHANGES_REQUIRED`, and record the failing check evidence.

#### Scenario: Unmodified worktree on completion claim
- **WHEN** an executor reports completion but `git status --porcelain` and `git diff` against base SHA show zero candidate file modifications
- **THEN** completion verification SHALL fail closed, classify the outcome as `NO_PROGRESS`, and prevent review invocation.

#### Scenario: Placeholder-only or fabricated candidate rejected
- **WHEN** an executor reports completion but the only worktree change is a placeholder artifact with no material implementation of the requested task
- **THEN** completion verification SHALL fail closed, classify the outcome as `NO_PROGRESS` or `EVIDENCE_INSUFFICIENT`, and prevent review invocation and any candidate-integrity claim.
