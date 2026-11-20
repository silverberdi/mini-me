## MODIFIED Requirements

### Requirement: Process-level agent write confinement boundary

Every agent process executing in an `EXECUTION_WORKTREE` (such as primary implementer, reviewer/auditor when writing, remediation, or integration agents) SHALL execute within an OS/process-level write confinement boundary that restricts persistent filesystem writes to the assigned worktree. On Linux Bubblewrap, each invocation SHALL additionally receive a private writable and ephemeral `/tmp` that is not backed by or shared with the host `/tmp`; temporary files created there SHALL be discarded when the invocation ends. The confined executor SHALL prevent supported build tools from leaving persistent build-server processes running after the invocation. These temporary runtime capabilities SHALL NOT permit writes to any other host path or make temporary files part of the candidate.

#### Scenario: Agent attempts shell write into RUNTIME checkout
- **GIVEN** an agent process executing inside an `EXECUTION_WORKTREE`
- **WHEN** the process issues a shell or filesystem write command targeting RUNTIME (e.g. `cd /opt/minime/app && touch file`)
- **THEN** the OS/process write confinement boundary SHALL block the syscall
- **AND** the write SHALL fail with permission denied without altering RUNTIME.

#### Scenario: Agent attempts absolute path write outside worktree
- **GIVEN** an agent process executing inside an `EXECUTION_WORKTREE`
- **WHEN** the process attempts to write to a persistent host path outside its assigned worktree (e.g. `/etc/config` or `/opt/minime/app/file`)
- **THEN** the OS/process write confinement boundary SHALL block the write syscall
- **AND** the write operation SHALL be denied.

#### Scenario: Linux Bubblewrap invocation uses isolated temporary storage
- **GIVEN** an agent or deterministic checks process executing under Linux Bubblewrap confinement
- **WHEN** it creates a temporary file or Unix-domain IPC socket under `/tmp`
- **THEN** creation and use SHALL succeed within that invocation's private temporary filesystem
- **AND** the host `/tmp` SHALL remain unchanged
- **AND** the temporary filesystem contents SHALL not be visible to another invocation and SHALL be discarded when the process exits.

#### Scenario: Confined build process does not leave a persistent build server
- **GIVEN** a confined invocation starts a supported build tool that can use a persistent background build server
- **WHEN** the invocation completes or fails
- **THEN** the tool SHALL not leave a build-server process running beyond the invocation
- **AND** the process SHALL release its IPC resources so the invocation can terminate.

#### Scenario: Agent attempts write through symlink pointing to RUNTIME
- **GIVEN** an agent process executing inside an EXECUTION_WORKTREE
- **WHEN** the process creates or traverses a symlink pointing from inside the worktree to a RUNTIME path
- **THEN** the OS/process write confinement boundary SHALL resolve the realpath and block the write syscall
- **AND** no RUNTIME file SHALL be modified.
