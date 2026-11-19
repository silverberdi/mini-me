## MODIFIED Requirements

### Requirement: Unified first-pass implementation convergence directive
The system SHALL dispatch the primary implementer with a unified, explicit execution directive instructing the agent to deliver all four vertical delivery components in a single session: (1) functional implementation code, (2) automated test coverage, (3) verification of deterministic checks passing with exit code 0, and (4) accurate updating of `tasks.md` checkboxes. The system SHALL require that marked task checkboxes are backed by non-planning implementation evidence in the worktree.

#### Scenario: Implementer converges on first pass for standard change
- **GIVEN** an admitted READY change assigned to the primary implementer
- **WHEN** native apply executes
- **THEN** the implementer receives the full change contract, target file paths, test commands, and task checklist instructions in its initial prompt harness
- **AND** the implementer authors functional code, adds tests, runs `pytest`, and updates `tasks.md` in that single invocation
- **AND** the engine evaluates completion without requiring intermediate manual or bookkeeping reconciliation attempts.

#### Scenario: Checkbox-only modification without functional code is rejected
- **GIVEN** an implementer invocation that marks tasks complete in `tasks.md` but introduces zero functional implementation or test files
- **WHEN** completion verification runs
- **THEN** the system rejects the attempt with diagnostic `IMPLEMENTATION_EVIDENCE_MISSING`
- **AND** the attempt is NOT marked as successful completion.

### Requirement: Precise recovery feedback preserving valid incremental progress
When an implementation attempt yields partial progress (e.g. valid functional code written but tests failing or tasks un-checked), the system SHALL NOT wipe the worktree or restart from a blank prompt. The subsequent corrective dispatch prompt SHALL provide precise diagnostic feedback specifying exactly what succeeded, what failed, and what remains to be completed.

#### Scenario: Corrective retry receives targeted diff and check failure feedback
- **GIVEN** an attempt that produced valid functional code but failed one specific test assertion in `pytest`
- **WHEN** the corrective retry attempt is prepared
- **THEN** the prompt preserves the candidate worktree state, cites the exact failing test name and stdout trace, and directs the implementer to fix only the failing test without rewriting the working code.
