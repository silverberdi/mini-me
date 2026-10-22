## Purpose
Expose only implemented provider capabilities centrally while storing independent ticket and Git/PR connections and authentication choices in each project.

## ADDED Requirements

### Requirement: Provider catalog metadata is separate from project connections
The provider catalog SHALL identify provider id, responsibility, implemented/unavailable status, supported operations, required typed fields, and supported authentication methods. It SHALL NOT contain project URLs, organizations, repository names, tokens, private keys, or operative project connections. F2 SHALL offer functional GitHub Issues ticket-source and GitHub Git/PR integrations only; Azure DevOps or another unimplemented provider SHALL be explicitly unavailable and unselectable.

#### Scenario: Read the provider catalog
- **WHEN** an authenticated operator queries the provider catalog
- **THEN** it lists the actual GitHub ticket and Git/PR capabilities and their required fields without exposing any project's connection or secret reference

#### Scenario: Select an unimplemented provider
- **WHEN** a project configuration selects an unavailable provider such as Azure DevOps
- **THEN** validation rejects it before persistence or any external side effect

### Requirement: Ticket-source and Git/PR connections are separate project-scoped values
Each project SHALL configure a ticket-source provider/connection and a Git/PR provider/connection independently, including endpoint/repository/branch as applicable, authentication mode, and safe credential reference. The two connections MAY use different repositories and SHALL NOT inherit a connection from another project. The only reusable connection permitted is an operator's explicit selection of mini me's existing GitHub `.env` credentials.

#### Scenario: Configure distinct GitHub repositories
- **WHEN** an operator configures GitHub Issues in repository A and Git/PR in repository B
- **THEN** each operation uses its own configured repository and connection without substituting one for the other

#### Scenario: Reject a non-remote or mismatched GitHub URL
- **WHEN** a project supplies a local path, `file:` URL, unsupported host/protocol, shorthand instead of a URL, or a URL whose normalized repository differs from the selected GitHub connection
- **THEN** validation rejects it before project persistence or GitHub/filesystem side effects

#### Scenario: Select shared environment credentials explicitly
- **WHEN** a project selects the existing GitHub `.env` credential mode
- **THEN** GitHub operations for that project use that shared installation identity only because of the explicit selection

#### Scenario: Use project-owned GitHub App credentials
- **WHEN** a project selects its own supported GitHub App and supplies project-local App/installation identifiers plus a protected host secret-file reference
- **THEN** the adapter verifies the App installation and required repository permissions using only that project's credential bundle

#### Scenario: Fail closed on invalid credentials or insufficient permissions
- **WHEN** the selected App/key/repository identity is invalid, unobservable, or lacks a required read/write/branch/push/PR permission
- **THEN** the connection is reported blocked with an actionable reason, no substitute credential is tried, and no protected mutation is attempted

### Requirement: Credential values remain outside project persistence and external output
Project configuration SHALL persist only authentication mode, non-secret identifiers, and a validated host-managed reference. Private-key bytes and installation tokens SHALL remain outside PostgreSQL, Git, ZIP content, agent input, API/CLI output, PRs, and logs. A project-owned secret reference SHALL resolve only within the configured host secret root and SHALL reject symlinks, traversal, and insecure file permissions.

#### Scenario: Credentials never appear in serialized surfaces
- **WHEN** a project is read, an error is logged, or an agent dispatch is prepared
- **THEN** secret bytes/tokens and sensitive credential contents are absent while authentication mode and a non-sensitive validation status remain observable

#### Scenario: Secret path escapes configured root
- **WHEN** a project-owned credential reference resolves outside the trusted secret root or through a symlink
- **THEN** validation fails before reading the key or invoking GitHub

### Requirement: Remote ticket source is authoritative without local ticket duplication
The ticket provider contract SHALL support listing, reading, creating, commenting on, and closing remote tickets required by the rector; GitHub Issues SHALL implement these operations in F2. F2 SHALL NOT select the oldest ticket or execute its OpenSpec lifecycle. Project configuration SHALL NOT use `backlog_path` or create a local PostgreSQL ticket queue.

#### Scenario: Configure GitHub Issues without a local backlog
- **WHEN** a project is created with GitHub Issues as its ticket source
- **THEN** the remote repository/connection is stored and verified and no ticket/backlog row is created in PostgreSQL

#### Scenario: Use GitHub Issue source operations
- **WHEN** an authorized caller uses the configured ticket-source contract to list/read/create/comment/close an Issue
- **THEN** the operation addresses the configured remote repository using that project's selected credential and returns a verified external result without writing a local ticket copy

#### Scenario: F2 does not select or execute a ticket
- **WHEN** a project is created or activated in F2
- **THEN** no Issue is selected for implementation and no agent OpenSpec lifecycle starts
