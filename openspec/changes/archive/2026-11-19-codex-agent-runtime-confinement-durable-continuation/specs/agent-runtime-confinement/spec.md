## ADDED Requirements

### Requirement: Attempt-private agent process state
The system SHALL execute implementer and reviewer processes under the existing operating-system confinement mechanism with the assigned execution worktree as the only writable code tree and a separate private, per-attempt writable runtime for required HOME, Codex, XDG, cache, and temporary state.

#### Scenario: Confined process writes code and private state
- **WHEN** an authorized agent process writes within its assigned worktree or attempt-private runtime
- **THEN** those writes succeed and the private runtime is inaccessible to unrelated attempts

#### Scenario: Confined process attempts host or unrelated writes
- **WHEN** an agent process attempts to write the runtime installation, managed checkout, another worktree, global HOME, host temporary directory, or an arbitrary host path
- **THEN** the operating-system confinement denies the write
- **AND** the system does not weaken mounts or fall back to an unconstrained process

#### Scenario: Attempt ends or is interrupted
- **WHEN** the agent process exits, fails to launch, times out, or is cancelled
- **THEN** the process group is reaped and the private runtime, including copied credentials, is removed

### Requirement: Authorized Codex credential projection
The system SHALL obtain Codex authentication only from the already-authorized service credential source and SHALL copy only the required credential file into the private attempt runtime with restrictive permissions. The persistent credential directory SHALL NOT be mounted writable or modified by the confined process.

#### Scenario: Credential source is unsafe or unavailable
- **WHEN** the authorized credential is absent, a symlink, unreadable, or has unsafe permissions
- **THEN** execution fails closed without exposing credential contents

#### Scenario: Credential rotates inside an attempt
- **WHEN** the private credential copy changes during execution and no authorized persistence mechanism can verify and store the rotation
- **THEN** the system reports an explicit blocked credential-rotation condition and does not overwrite persistent credentials

### Requirement: Local confinement failures are environment failures
The system SHALL classify positively identified local sandbox filesystem or required-path initialization failures as `ENVIRONMENT_UNAVAILABLE`, while preserving higher-priority authentication, quota, rate-limit, and policy classifications. It SHALL NOT classify an arbitrary unknown error as an environment failure.

#### Scenario: Local sandbox initialization fails
- **WHEN** initialization reports a recognized read-only filesystem or missing private runtime path
- **THEN** the outcome is `ENVIRONMENT_UNAVAILABLE`
- **AND** provider health, corrective retry budget, and executor assignment are not penalized

#### Scenario: Unrecognized error occurs
- **WHEN** output contains only an unrecognized generic error
- **THEN** it remains an unknown/provider result and is not inferred to be an environment failure

#### Scenario: Codex app-server initialize handshake
- **WHEN** the real Codex CLI app-server receives only a JSON-RPC `initialize` request inside Linux Bubblewrap
- **THEN** it returns the initialization response without a read-only-filesystem error
- **AND** no model turn is started
