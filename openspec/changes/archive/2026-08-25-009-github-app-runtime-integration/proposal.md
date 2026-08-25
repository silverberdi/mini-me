## Why

Prior changes (001–008) established autonomous change orchestration, review/audit governance, and worktree isolation, but GitHub operations accidentally depended on the local `gh` CLI authenticated under the operator's personal GitHub account, while Issue validation only verified local integer formats without proving remote existence or repository ownership. Change 009 makes the configured GitHub App the canonical runtime identity for all GitHub API and Git push operations, removing personal credential coupling and establishing verified remote work binding before autonomous self-orchestration begins.

## What Changes

- Implement canonical GitHub App authentication using configured App ID, Installation ID, and Private Key (`MINIME_GITHUB_APP_ID`, `MINIME_GITHUB_INSTALLATION_ID`, `MINIME_GITHUB_PRIVATE_KEY_PATH`).
- Generate short-lived installation access tokens via standard RS256 JWT exchange, cached strictly in memory with expiration tracking, and never persisted to PostgreSQL, Git, configuration, logs, or durable events.
- Replace subprocess `gh` CLI invocations in the GitHub adapter with direct HTTP API operations authenticated under the GitHub App installation token.
- Add remote GitHub Issue validation during Definition of Ready and binding evaluation to prove the Issue exists and belongs to the registered project repository.
- Implement ephemeral GitHub App authentication for Git branch push and remote reference queries without persisting tokens to remotes, repository Git config, shell history, or process diagnostics.
- Preserve explicit repository authority from durable project bindings and prevent presentation metadata from influencing execution repositories.
- Preserve authoritative PR lookup states (`NOT_FOUND`, `FOUND_EXACT`, `UNOBSERVABLE`, `AMBIGUOUS`) and ensure ambiguous push/PR outcomes are reconciled before retry without blind retries.
- Enforce fail-closed behavior when App credentials are missing, invalid, or unauthorized, strictly prohibiting silent fallback to the operator's personal `gh` session.
- Provide machine-readable diagnostics distinguishing authorization failures, transient unobservability, repository mismatches, Issue mismatches, and PR ambiguities without exposing secret material.

## Capabilities

### New Capabilities

- `github-app-runtime-identity`: Canonical GitHub App authentication, short-lived installation token lifecycle, and secret-safe runtime Git push authorization.

### Modified Capabilities

- `github-work-binding`: Bind GitHub operations (Issue existence/repository validation, PR lookup/reconciliation, PR creation, Git push) to the canonical GitHub App installation identity, eliminating reliance on personal `gh` CLI credentials.
- `openspec-readiness`: Require remote GitHub Issue verification (existence and repository ownership via GitHub App runtime identity) during Definition of Ready evaluation.
- `status-observability`: Expose GitHub App runtime authentication state and machine-readable reconciliation/auth failure diagnostics without disclosing secrets or token material.

## Impact

- `src/minime/adapters/github.py` is upgraded to use direct HTTP REST API calls (`httpx`) authenticated with GitHub App installation tokens, replacing `subprocess` calls to `gh`.
- A dedicated authentication component handles RS256 JWT generation from the private key and ephemeral token retrieval/caching.
- `src/minime/services/readiness_service.py` evaluates real remote Issue existence and repository ownership through the authenticated adapter.
- Git push execution uses ephemeral configuration headers (e.g. `http.extraHeader`) in subprocess environment/arguments without modifying repo remotes or writing tokens to disk.
- No historical Alembic migrations (001–008) are modified; no new database schema changes are required as token state is ephemeral in-memory.
- Existing regression tests remain green, and new unit/adapter tests verify App authentication, token safety, absence of personal `gh` fallback, and isolated Git/GitHub error states.
