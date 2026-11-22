## ADDED Requirements

### Requirement: Apply candidate is committed and frozen before Verify
After native Apply or an Apply correction completes, the system SHALL run the applicable candidate tests and, only after they pass, establish an immutable Git commit for the resulting candidate before dispatching native Verify. The Run's candidate identity and Verify invocation SHALL reference that exact commit SHA. The commit SHALL include only changes belonging to the candidate and SHALL NOT absorb unrelated workspace changes. Failed tests or an unobservable/failed commit SHALL prevent Verify dispatch and preserve the candidate for recovery. If Verify or a later correction changes candidate files, the changed candidate SHALL pass its applicable tests and be committed as a new SHA before Verify is dispatched again.

#### Scenario: Passing Apply candidate is frozen before Verify
- **GIVEN** native Apply or its correction has completed and the applicable candidate tests pass
- **WHEN** the Run is ready to dispatch native Verify
- **THEN** the candidate changes are committed on the existing candidate branch
- **AND** the Run records the resulting commit SHA as the candidate identity
- **AND** Verify is dispatched against that exact SHA.

#### Scenario: Test or commit failure prevents Verify dispatch
- **GIVEN** the candidate tests fail, Git cannot create or observe the candidate commit, or the resulting workspace still contains unaccounted candidate changes
- **WHEN** the Run is ready to dispatch Verify
- **THEN** Verify is not dispatched
- **AND** the Run preserves the worktree and records the observed failure for recovery.

#### Scenario: Unrelated workspace changes are excluded
- **GIVEN** unrelated staged or unstaged files are present in the candidate worktree
- **WHEN** the system creates the immutable candidate commit
- **THEN** those unrelated files are not included
- **AND** the Run does not claim a clean frozen candidate until its own changes and SHA are verified.

#### Scenario: A correction after the frozen commit requires a new candidate SHA
- **GIVEN** Verify or an authorized subsequent correction changes candidate files after a commit was recorded
- **WHEN** Verify is to be dispatched for the corrected candidate
- **THEN** the system runs the applicable tests and records a new commit SHA for the changed candidate
- **AND** it does not present the prior SHA as the corrected candidate.
