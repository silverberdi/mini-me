## ADDED Requirements

### Requirement: Process-Private Bytecode Compilation Cache
The system SHALL isolate bytecode cache generation to a process-private or runtime-isolated directory owned by the current process execution identity and SHALL NOT rely on shared, world-accessible, or predictable multi-user `/tmp` paths prone to permission collisions or symlink pre-creation attacks across different OS users.

#### Scenario: Deterministic checks execute under non-root service user
- **WHEN** deterministic checks execute for a candidate worktree under service user `minime`
- **THEN** bytecode compilation cache path (`PYTHONPYCACHEPREFIX`) is placed inside a private runtime path (`~/.cache/minime/pycache/<job_id>`) or securely generated private directory owned by `minime`
- **AND** no `PermissionError` occurs due to preexisting directories owned by verification operator or other users in `/tmp`.

#### Scenario: Recursive permissions modification strictly prohibited
- **WHEN** initializing check runner or execution environment
- **THEN** the system SHALL NOT execute `chown -R` or `chmod 1777` on shared system directories such as `/tmp` or shared parent paths.

#### Scenario: Symlink or improper ownership pre-creation rejected
- **WHEN** the designated cache path exists on the host
- **AND** the path is a symlink or is owned by a different UID or has loose permissions
- **THEN** `ChecksRunner` SHALL reject the unsafe path fail-closed and re-create a private directory with mode `0700` owned by the executing process UID.

### Requirement: Bubblewrap Sandbox Private Cache Bind Mount
When execution confinement is active using Bubblewrap (`bwrap`), the system SHALL mount the private bytecode cache directory as a read-write bind mount in the container sandbox without permitting unrestricted user-supplied extra bind paths or broad writable host paths.

#### Scenario: Checks execution under Bubblewrap with bytecode compilation
- **WHEN** a check subprocess is launched inside Bubblewrap confinement
- **THEN** the validated private cache directory is mounted read-write (`--dir <sandbox_cache_dir> --bind <host_cache_dir> <sandbox_cache_dir>`)
- **AND** the sandbox process can write bytecode `.pyc` files without escaping confinement or failing with `Permission denied`.
- **AND** the candidate worktree remains completely clean and porcelain-unmodified after check completion.
