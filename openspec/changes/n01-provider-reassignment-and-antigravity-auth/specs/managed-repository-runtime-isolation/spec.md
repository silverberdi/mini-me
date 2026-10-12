## ADDED Requirements

### Requirement: Antigravity credentials are projected into private agent runtime
When the Antigravity CLI requires host authentication, the confinement runtime SHALL project only the explicitly authorized Antigravity authentication file into a private per-process runtime, without mounting the host HOME or the broader `.gemini` directory.

#### Scenario: Authenticated non-inference CLI check in confined runtime
- **GIVEN** a valid authorized Antigravity auth file and an OS-enforced Bubblewrap runtime
- **WHEN** the real `agy models` command is run in the private runtime
- **THEN** it SHALL authenticate without invoking inference
- **AND** unrelated host files, host credential directories, runtime, and other worktrees SHALL remain inaccessible for writes.

#### Scenario: Access-token-only refresh is tolerated without persisting secrets
- **GIVEN** the private Antigravity OAuth document has an unchanged nonempty refresh_token, token_type, all other token fields, and root metadata
- **WHEN** the process updates only token.access_token and/or token.expiry
- **THEN** the runtime SHALL record a private credential refresh, redact both original and newly issued secrets from returned output, and allow the otherwise successful provider result
- **AND** the private runtime SHALL be destroyed without changing the host credential source.

#### Scenario: Unexpected or refresh-authority rotation fails closed
- **GIVEN** the confined process changes the refresh_token, other OAuth fields, document structure, or removes its private auth copy
- **WHEN** the process completes or is cancelled
- **THEN** the runtime SHALL flag an unsafe unpersisted credential rotation, suppress child output, report provider environment failure, and leave the persistent credential unchanged.

#### Scenario: Missing or unsafe credential authority fails closed
- **GIVEN** the configured Antigravity credential source is missing, a symlink, unreadable, or has unsafe permissions
- **WHEN** runtime creation is requested
- **THEN** confinement SHALL fail closed before launching the CLI.
