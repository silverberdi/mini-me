## ADDED Requirements

### Requirement: Standard virtual sandbox devices under Bubblewrap confinement
Under Linux Bubblewrap process confinement, the execution boundary SHALL mount an unprivileged virtual `/dev` exposing standard virtual devices (`/dev/null`, `/dev/zero`, `/dev/urandom`, `/dev/pts`) required by standard POSIX runtimes and test frameworks, while keeping all host root paths read-only and filesystem writes strictly restricted to the assigned candidate worktree.

#### Scenario: Subprocess opens /dev/null inside Bubblewrap sandbox
- **GIVEN** an agent or deterministic checks runner subprocess executing inside a Bubblewrap confinement boundary
- **WHEN** the process opens `/dev/null` for reading or writing (e.g. pytest capture manager or standard shell redirection)
- **THEN** the operation SHALL succeed without `PermissionError` or `EACCES`
- **AND** the exit code SHALL NOT be 126 or 127 due to missing or blocked device nodes.

#### Scenario: Subprocess write outside worktree remains blocked
- **GIVEN** an agent or checks runner subprocess executing inside Bubblewrap with `/dev` mounted
- **WHEN** the subprocess attempts to write to `/etc`, `/usr`, `/opt/minime/app`, or any host path outside the assigned worktree
- **THEN** the confinement boundary SHALL block the write operation
- **AND** the write operation SHALL fail with permission denied (e.g. read-only filesystem or EACCES).

#### Scenario: Real test execution inside Bubblewrap sandbox
- **GIVEN** a candidate worktree containing Python deterministic tests requiring standard capture
- **WHEN** `ChecksRunner` executes the test suite under real Linux Bubblewrap confinement with `--dev /dev`
- **THEN** all tests SHALL execute and capture standard streams cleanly
- **AND** the process return code SHALL reflect the true test execution outcome (0 on pass).

#### Scenario: Non-Linux platforms preserve existing confinement
- **GIVEN** the confinement service executing on macOS (Darwin) or platforms without Bubblewrap
- **WHEN** `wrap_command` is invoked
- **THEN** the platform-specific confinement mechanism (e.g. `darwin_sandbox`) SHALL be used without attempting to invoke `bwrap`
- **AND** no Linux-specific flags SHALL be injected.
