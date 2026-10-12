## ADDED Requirements

### Requirement: Private Bubblewrap runtime retains verified DNS configuration
The system SHALL keep `/run` private to an agent process and SHALL expose only the verified host resolver file required for name resolution, read-only, when the resolver target would otherwise be hidden by the private `/run` mount.

#### Scenario: Resolver target is hidden by private `/run`
- **WHEN** the effective path required by `/etc/resolv.conf` is beneath host `/run` and would be hidden
- **AND** its resolved target is a readable regular file
- **THEN** Bubblewrap SHALL project only that exact file read-only after creating its private `/run`
- **AND** the agent SHALL be able to resolve host names when network access is otherwise available
- **AND** no other host `/run` paths or sockets SHALL be exposed

#### Scenario: Resolver target is outside host `/run`
- **WHEN** `/etc/resolv.conf` resolves to a readable regular file outside `/run`
- **THEN** the existing read-only host-root view SHALL provide it without an additional mount

#### Scenario: Resolver target is unsafe or unverifiable
- **WHEN** the resolver target is missing, unreadable, not a regular file, or conflicts with the private agent runtime
- **THEN** confined process setup SHALL fail closed

#### Scenario: Agent attempts to modify resolver configuration
- **WHEN** an agent process attempts to write the projected resolver file or any host `/run` path outside its private runtime
- **THEN** the operating system SHALL deny the write

#### Scenario: Explicit network isolation remains requested
- **WHEN** a caller requests network isolation for a confined diagnostic process
- **THEN** Bubblewrap SHALL continue to apply `--unshare-net`
