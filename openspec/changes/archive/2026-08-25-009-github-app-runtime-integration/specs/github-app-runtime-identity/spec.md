## Purpose

Establishes the configured GitHub App as the canonical runtime identity for GitHub API and Git push operations, managing ephemeral in-memory installation tokens with strict credential protection and zero fallback to operator personal authentication.

## ADDED Requirements

### Requirement: Canonical GitHub App authentication
The system SHALL authenticate to GitHub using the configured GitHub App ID, installation ID, and private key, generating short-lived RS256 JSON Web Tokens (JWT) to obtain installation access tokens from the GitHub REST API.

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

### Requirement: Ephemeral in-memory token lifecycle
The system SHALL cache installation tokens strictly in volatile memory respecting token expiration and SHALL NOT persist tokens or private key material to PostgreSQL, Git, configuration files, logs, durable events, or process diagnostics.

#### Scenario: Active token is reused until near expiry
- **GIVEN** a cached installation token exists in memory with valid remaining lifetime
- **WHEN** a subsequent GitHub operation is requested before expiration threshold
- **THEN** the cached token is reused without generating a new JWT or installation token request.

#### Scenario: Expired token is refreshed automatically
- **GIVEN** a cached installation token has expired or is within the refresh window
- **WHEN** a GitHub operation is initiated
- **THEN** a new installation token is requested using the App private key and stored in memory.

#### Scenario: Token is never persisted or logged
- **GIVEN** GitHub authentication and API operations occur during execution
- **WHEN** operational logs, exceptions, process diagnostics, database transactions, or durable events are recorded
- **THEN** installation access tokens and private key contents are completely redacted.

### Requirement: Secret-safe Git push authorization
The system SHALL authenticate runtime Git push and remote inspection operations using ephemeral GitHub App installation authorization bound to the registered repository and exact candidate SHA without writing credentials to repository Git config or persistent remotes.

#### Scenario: Git push authenticates via ephemeral App credentials
- **GIVEN** a candidate is frozen, audited, and ready for branch push
- **WHEN** the GitHub adapter executes a git push to the registered remote
- **THEN** authentication is injected ephemerally for the subprocess invocation
- **AND** only the exact candidate SHA is pushed to the bound branch.

#### Scenario: Git push does not persist secrets to Git remotes or config
- **GIVEN** a git push operation completes, fails, or is interrupted
- **WHEN** `.git/config`, persistent remotes, or process diagnostics are inspected
- **THEN** no installation token or secret material is persisted in the repository or worktree.

### Requirement: Strict identity isolation from personal credentials
The system SHALL NOT use or fall back to the operator's personal `gh` session or ambient personal git credentials for runtime orchestration operations.

#### Scenario: Personal gh authentication is present but ignored
- **GIVEN** the host environment has an active `gh` CLI login for a personal GitHub account
- **WHEN** mini me evaluates readiness, validates issues, looks up PRs, creates PRs, or pushes branches
- **THEN** all operations execute exclusively under the GitHub App installation identity.

#### Scenario: App authentication failure does not fall back
- **GIVEN** GitHub App authentication fails or is unconfigured
- **AND** the operator's personal `gh` CLI session is valid and authenticated
- **WHEN** a GitHub operation is attempted
- **THEN** the operation fails closed and does not attempt execution under the personal account.
