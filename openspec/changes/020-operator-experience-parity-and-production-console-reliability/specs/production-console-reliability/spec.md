# spec: production-console-reliability

## Purpose
Ensure the mini me CLI and interactive TUI console (`minime console`, `minime status`) can be launched reliably in production over SSH without manual environment exports, credential exposure, or security regressions.

## Requirements

### Requirement 1: Canonical Environment Discovery
The configuration subsystem MUST automatically discover and load environment definitions from canonical sources if not already set in the current process environment.
- Discovery order:
  1. `MINIME_CONFIG_PATH`
  2. `MINIME_ENV_FILE`
  3. `/etc/minime/minime.env`
  4. `.env` in current directory
- Files MUST be parsed safely without executing arbitrary shell code.
- Existing environment variables MUST NOT be overridden (`os.environ.setdefault`).

#### Scenario: Running TUI in fresh SSH shell
- **GIVEN** an SSH login shell as user `silverman` with no manual environment exports
- **AND** `/etc/minime/minime.env` exists and is readable by the `minime` group
- **WHEN** the operator executes `minime console` or `minime status`
- **THEN** the CLI automatically discovers `/etc/minime/minime.env`
- **AND** connects to PostgreSQL without throwing `Database URL is not configured`.

### Requirement 2: Secure Production Launcher & Group Permissions
Production servers MUST provide a canonical launcher in system PATH (`/usr/local/bin/minime`) that invokes the production runtime virtualenv.
- `/etc/minime/minime.env` MUST maintain group-restricted permissions (`0640 minime:minime`).
- Secrets MUST NOT be made world-readable.
- Secrets MUST NOT be printed to stdout/stderr or stored in shell history.

#### Scenario: Production launcher invocation
- **GIVEN** `/usr/local/bin/minime` installed on the server
- **WHEN** an operator in group `minime` runs `minime status`
- **THEN** system status and health are displayed cleanly
- **AND** no credentials appear in shell history or command output.
