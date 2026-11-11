## Purpose

Allow an operator to end an active, human-gated Mini Me Run through supported interfaces so it releases the project's active Run slot without direct database edits.

## ADDED Requirements

### Requirement: Operator can cancel an eligible active Run

Mini Me SHALL expose authenticated API and CLI operations to cancel a specific active Run when no stage job is active. A successful cancellation SHALL set the Run outcome to `CANCELLED`, clear its human gate, set it inactive, retain its existing stop details, and record the operator, reason, and time. The transition SHALL release the project's active Run slot and use the existing worktree ownership and cleanup rules.

#### Scenario: Cancel an active Run with no job
- **GIVEN** the Run is active and has no active stage job
- **WHEN** an authenticated operator cancels that Run with a reason
- **THEN** the Run becomes inactive with outcome `CANCELLED` and no human gate
- **AND** its prior stop details remain available with cancellation actor, reason, and time recorded
- **AND** the project can admit its next eligible Issue
- **AND** worktree cleanup follows the repository's durable ownership checks

#### Scenario: Reject cancellation for the wrong project or Run
- **GIVEN** the Run does not belong to the requested project
- **WHEN** an operator requests cancellation
- **THEN** Mini Me returns not found or conflict without mutating the Run or its job

#### Scenario: Reject an executing or terminal Run
- **GIVEN** the Run has an active stage job or has a terminal outcome
- **WHEN** an operator requests cancellation
- **THEN** Mini Me fails closed with a clear conflict and preserves the Run, job, gate, and workspace

#### Scenario: Handle a repeated cancellation safely
- **GIVEN** the same cancellation request was already accepted
- **WHEN** it is submitted again with the same idempotency key
- **THEN** Mini Me returns the recorded result without adding another transition or cleanup
- **AND** a different request cannot cancel an inactive or terminal Run

### Requirement: Cancellation is available from operator interfaces

The current Run view SHALL present a cancellation action only for an eligible human-gated Run, explain that cancellation ends the Run, and require explicit confirmation before submission. The CLI SHALL target a specific Run and require a reason. Both interfaces SHALL show success or a clear failure without implying that the Run was canceled if the server rejected the operation.

#### Scenario: Confirm cancellation in the current Run view
- **GIVEN** an eligible human-gated Run is visible in the PWA
- **WHEN** the operator selects cancel and confirms the action
- **THEN** the UI submits the targeted Run cancellation and displays the server's result

#### Scenario: Operator declines cancellation
- **GIVEN** the cancellation confirmation is open
- **WHEN** the operator declines
- **THEN** no cancellation request is sent and the Run remains unchanged
