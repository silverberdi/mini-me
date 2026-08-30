## MODIFIED Requirements

### Requirement: Secret-safe Git push authorization
The system SHALL authenticate runtime Git push and remote inspection operations using ephemeral GitHub App installation authorization bound to the registered repository and exact candidate SHA without writing credentials to repository Git config or persistent remotes, and SHALL strip inherited Git diagnostic and trace environment variables before launching authenticated Git subprocesses.

#### Scenario: Git push authenticates via ephemeral App credentials
- **GIVEN** a candidate is frozen, audited, and ready for branch push
- **WHEN** the GitHub adapter executes a git push to the registered remote
- **THEN** authentication is injected ephemerally for the subprocess invocation
- **AND** only the exact candidate SHA is pushed to the bound branch.

#### Scenario: Inherited Git trace variables stripped before authenticated Git execution
- **GIVEN** ambient Git trace environment variables (`GIT_TRACE`, `GIT_TRACE_PACKET`, `GIT_TRACE_CURL`, `GIT_CURL_VERBOSE`, `GIT_TRANSPORT_TRACE`) are set in the runtime environment
- **WHEN** authenticated Git subprocesses (e.g. `push`, `ls-remote`) are executed
- **THEN** the adapter SHALL purge all trace variables from the subprocess environment before execution
- **AND** HTTP Authorization headers containing token material cannot be dumped to trace streams.

#### Scenario: Git push does not persist secrets to Git remotes or config
- **GIVEN** a git push operation completes, fails, or is interrupted
- **WHEN** `.git/config`, persistent remotes, or process diagnostics are inspected
- **THEN** no installation token or secret material is persisted in the repository or worktree.

### Requirement: Canonical GitHub App authentication
The system SHALL authenticate to GitHub using the configured GitHub App ID, installation ID, and private key, generating short-lived RS256 JSON Web Tokens (JWT) to obtain installation access tokens from the GitHub REST API, and SHALL rely on authoritative remote Issue verification for repository validation without redundant standalone repository queries.

#### Scenario: Valid GitHub App credentials generate installation token
- **GIVEN** valid GitHub App ID, installation ID, and private key path configured in the host environment
- **WHEN** the GitHub adapter initiates an authenticated GitHub API or Git operation
- **THEN** an RS256 JWT is signed with the private key
- **AND** a short-lived installation access token is retrieved from GitHub for the bound installation.

#### Scenario: Missing or invalid App credentials fail closed
- **GIVEN** one or more of App ID, installation ID, or private key path are missing, inaccessible, or invalid
- **WHEN** the system attempts GitHub authentication
- **THEN** the operation fails closed with a structured authorization failure
- **AND** the system does not fall back to personal `gh` CLI credentials or default host git credentials.

#### Scenario: Installation authorization failure fails closed
- **GIVEN** the private key is valid but the installation ID is revoked, mismatched, or unauthorized for the target repository
- **WHEN** the system requests an installation access token or repository operation
- **THEN** the request fails closed with a structured authorization refusal.
