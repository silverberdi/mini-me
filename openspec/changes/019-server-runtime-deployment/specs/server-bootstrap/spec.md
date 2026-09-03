# Spec: Server Bootstrap (019.1)

## ADDED REQUIREMENTS

### Requirement: Canonical Directory Structure
The server environment MUST maintain separated canonical directories for application code, runtime virtual environments, configuration, secrets, operational logs, and managed worktrees.

#### Scenario: Verify Canonical Paths
- Given the Linux server `192.168.0.194`
- When directory structure is inspected
- Then `/opt/minime/app`, `/opt/minime/runtime`, `/etc/minime/secrets`, `/var/lib/minime/worktrees`, `/var/lib/minime/state`, and `/var/log/minime` exist with ownership `minime:minime` and appropriate permission bits (`0700` for `secrets/`).

### Requirement: Dedicated Service User
The production runtime MUST run under a dedicated unprivileged system account `minime` with membership in the `docker` group.

#### Scenario: Service User Verification
- Given the system user `minime`
- When user attributes and groups are inspected
- Then the user has a non-login shell (`/usr/sbin/nologin`), belongs to `minime` and `docker` groups, and is not root.

### Requirement: Production Python Runtime & CLI
The server MUST provide a dedicated Python virtualenv containing the `minime` package and CLI entrypoint.

#### Scenario: Mini Me CLI Execution
- Given the virtualenv at `/opt/minime/runtime/venv`
- When running `/opt/minime/runtime/venv/bin/minime --help`
- Then the command exits 0 and displays the canonical subcommands (`orchestrate`, `scheduler`, `queue`, `providers`, `budget`, `doctor`).

### Requirement: Database & Provider Connectivity
The server runtime MUST connect to the canonical PostgreSQL instance (`127.0.0.1:5432/minime`) and verify provider interfaces.

#### Scenario: Database & Provider Probing
- Given `/etc/minime/minime.env` and `/etc/minime/minime.yaml`
- When checking database connectivity and provider CLI status
- Then PostgreSQL responds with Alembic revision `016_provider_efficiency_telemetry`, DeepSeek API responds to read-only ping, and Codex CLI is executable.
