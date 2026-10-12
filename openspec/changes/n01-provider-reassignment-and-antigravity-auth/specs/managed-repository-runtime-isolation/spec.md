## ADDED Requirements

### Requirement: Antigravity credentials are projected into private agent runtime
When the Antigravity CLI requires host authentication, the confinement runtime SHALL project only the explicitly authorized Antigravity authentication file into a private per-process runtime, without mounting the host HOME or the broader `.gemini` directory.

#### Scenario: Authenticated non-inference CLI check in confined runtime
- **GIVEN** a valid authorized Antigravity auth file and an OS-enforced Bubblewrap runtime
- **WHEN** the real `agy models` command is run in the private runtime
- **THEN** it SHALL authenticate without invoking inference
- **AND** unrelated host files, host credential directories, runtime, and other worktrees SHALL remain inaccessible for writes.

#### Scenario: Credential rotation cannot silently modify persistent credentials
- **GIVEN** the confined process changes or removes its private Antigravity auth copy
- **WHEN** the process exits or is cancelled
- **THEN** the runtime SHALL report an unpersisted credential rotation, scrub output that could contain new secrets, destroy the private runtime, and leave the host credential source unchanged.

#### Scenario: Missing or unsafe credential authority fails closed
- **GIVEN** the configured Antigravity credential source is missing, a symlink, unreadable, or has unsafe permissions
- **WHEN** runtime creation is requested
- **THEN** confinement SHALL fail closed before launching the CLI.
