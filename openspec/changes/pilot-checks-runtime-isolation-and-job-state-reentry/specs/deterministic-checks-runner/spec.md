## ADDED Requirements

### Requirement: Process-Private Bytecode Compilation Cache
The system SHALL isolate bytecode cache generation to a process-private or runtime-isolated directory owned by the current process execution identity and SHALL NOT rely on shared, world-accessible or multi-user `/tmp` paths prone to permission collisions across different OS users.

#### Scenario: Deterministic checks execute under non-root service user
- **WHEN** deterministic checks execute for a candidate worktree under service user `minime`
- **THEN** bytecode compilation cache path (`PYTHONPYCACHEPREFIX`) is placed inside a private runtime path or process-isolated directory owned by `minime`
- **AND** no `PermissionError` occurs due to preexisting directories owned by verification operator or other users in `/tmp`.

#### Scenario: Recursive permissions modification strictly prohibited
- **WHEN** initializing check runner or execution environment
- **THEN** the system SHALL NOT execute `chown -R` or `chmod 1777` on shared system directories such as `/tmp` or shared parent paths.

### Requirement: Bubblewrap Sandbox Private Cache Bind Mount
When execution confinement is active using Bubblewrap (`bwrap`), the system SHALL mount the private bytecode cache directory as a read-write bind mount in the container sandbox.

#### Scenario: Checks execution under Bubblewrap with bytecode compilation
- **WHEN** a check subprocess is launched inside Bubblewrap confinement
- **THEN** the designated `PYTHONPYCACHEPREFIX` directory is mounted read-write (`--bind <host_cache_dir> <sandbox_cache_dir>`)
- **AND** the sandbox process can write bytecode `.pyc` files without escaping confinement or failing with `Permission denied`.
