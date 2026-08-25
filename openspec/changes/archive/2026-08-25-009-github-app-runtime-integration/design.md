## Context

Prior changes (001–008) established autonomous change orchestration, review/audit governance, candidate freezing, and worktree isolation, but GitHub API operations still relied on the operator's personal `gh` CLI credentials via subprocesses, and Issue validation only verified local integer formats without querying remote existence. Change 009 transitions all runtime GitHub operations to the configured GitHub App identity (`MINIME_GITHUB_APP_ID`, `MINIME_GITHUB_INSTALLATION_ID`, `MINIME_GITHUB_PRIVATE_KEY_PATH`), establishing canonical runtime authority with ephemeral in-memory token lifecycle, secret-safe Git push, and remote work validation. See proposal.md for motivation and non-goals.

## Goals / Non-Goals

**Goals:**

- Implement canonical GitHub App authentication generating RS256 JWTs and obtaining ephemeral installation access tokens via GitHub REST API.
- Provide a direct HTTP REST API client (`httpx`) within `GitHubAdapter` replacing subprocess `gh` CLI calls.
- Enforce remote Issue validation proving Issue existence and repository ownership during Definition of Ready and binding evaluation.
- Implement secret-safe Git push and remote reference queries using ephemeral authorization headers without writing credentials to repository Git config or persistent remotes.
- Preserve 008 authoritative PR lookup states (`NOT_FOUND`, `FOUND_EXACT`, `UNOBSERVABLE`, `AMBIGUOUS`) and reconciliation semantics.
- Fail closed when GitHub App credentials are missing, invalid, or unauthorized, strictly prohibiting fallback to personal `gh` credentials.
- Ensure zero leakage of private keys or installation tokens into database, Git remotes, configuration files, logs, durable events, or process diagnostics.

**Non-Goals:**

- Automatic PR merge, auto-archive, deployment, scheduling, or multi-project concurrency.
- Webhook ingestion or GitHub Actions orchestration redesign.
- Multi-tenant or org-wide GitHub App installation management.
- Modifying historical Alembic migrations (001–008) or introducing unnecessary database schema changes.
- Residual hardening from 007/008 (reserved for subsequent hardening change).

## Decisions

### 1. Dedicated GitHub App authentication client with volatile token caching

The system introduces a dedicated `GitHubAppAuth` helper (or integrated auth service within the adapter) that:
- Reads the App ID, Installation ID, and RSA private key from host-controlled paths (`MINIME_GITHUB_PRIVATE_KEY_PATH`).
- Signs an RS256 JWT with payload:
  - `iat`: `int(time.time()) - 60` (60-second clock drift allowance)
  - `exp`: `int(time.time()) + (9 * 60)` (9-minute lifetime, within GitHub's 10-minute limit)
  - `iss`: `str(app_id)`
- Requests an installation access token via `POST https://api.github.com/app/installations/{installation_id}/access_tokens`.
- Caches the returned token in volatile memory alongside its `expires_at` timestamp.
- Automatically refreshes the token if a request is initiated when remaining lifetime is under 60 seconds.
- Fails closed with structured `GitHubAuthorizationError` if credentials are unconfigured, invalid, expired, or rejected.

*Alternatives considered:*
- *Subprocess `gh auth token`:* Rejected because it binds execution to the operator's personal interactive CLI session rather than the authorized runtime App identity.
- *Heavy third-party SDK (e.g. PyGithub):* Rejected because `httpx` and `PyJWT` are already installed and provide complete control over token lifecycle, timeout, and secret redaction.

### 2. Direct HTTP REST API client for repository, Issue, and PR operations

The `GitHubAdapter` communicates directly with GitHub's REST API (`https://api.github.com`) using `httpx.Client` authenticated via `Authorization: Bearer <installation_token>`:
- **Repository Validation:** `GET /repos/{owner}/{repo}` verifies repository existence and App accessibility.
- **Issue Existence & Ownership:** `GET /repos/{owner}/{repo}/issues/{issue_number}` verifies that the issue exists, is accessible, and belongs strictly to the bound repository.
- **PR Lookup:** `GET /repos/{owner}/{repo}/pulls?head={owner}:{branch}&base={base}&state=all` returns matching PRs:
  - 0 records → `NOT_FOUND`
  - 1 matching record → `FOUND_EXACT`
  - >1 records or unparseable response → `AMBIGUOUS`
  - Network / 5xx / 429 rate limit → `UNOBSERVABLE`
- **PR Creation:** `POST /repos/{owner}/{repo}/pulls` creates a new PR only when lookup is `NOT_FOUND`, and verifies that the created PR head SHA matches the audited candidate SHA before returning.

*Alternatives considered:*
- *Retaining `gh pr list` / `gh pr create` with `GH_TOKEN` environment variable:* Rejected to eliminate CLI subprocess parsing quirks, ensure clean timeout handling, and guarantee no fallback to ambient personal credentials.

### 3. Ephemeral Git push authentication without remote modification

Runtime Git push operations in `GitHubAdapter.push_branch` and remote queries in `get_remote_branch_head`:
- Maintain the repository remote URL as standard HTTPS (`https://github.com/{owner}/{repo}.git`) without embedding credentials into `.git/config` or persistent remotes.
- Pass authentication ephemerally per command invocation using Git configuration overrides:
  `git -c http.extraHeader="Authorization: Basic <base64(x-access-token:TOKEN)>"` (or bearer header equivalent) executed directly in the subprocess arguments.
- Strictly enforce the repository root validation and exact candidate SHA refspec (`{candidate_sha}:refs/heads/{branch}`) established in 008.
- Sanitized logging ensures that command execution strings containing `http.extraHeader` or authorization tokens are scrubbed before reaching loggers or error diagnostics.

*Alternatives considered:*
- *Embedding token in remote URL (`https://x-access-token:TOKEN@github.com/...`):* Rejected because token leaks into `.git/config`, `git remote -v`, and shell diagnostics.
- *Writing to Git credential helper:* Rejected because it risks lingering credential persistence on the host filesystem.

### 4. Remote Issue validation in ReadinessService

`ReadinessService.evaluate_change_readiness` is updated to invoke `github_adapter.validate_issue_binding` with remote verification enabled:
- The adapter queries GitHub API for the bound issue number against the project repository.
- If the issue does not exist (404), the check returns `passed=False` with reason `"GitHub Issue #{number} does not exist in repository '{repository}'."`
- If the issue belongs to a different repository or is mismatched, the check returns `passed=False` with reason `"Repository mismatch: GitHub Issue #{number} belongs to '{actual}', not '{expected}'."`
- If the remote is unobservable (transient network/server error), the check reports unobservability so orchestration can distinguish transient outages from permanent binding errors.

### 5. Strict fail-closed isolation from personal credentials

- If GitHub App configuration (`MINIME_GITHUB_APP_ID`, `MINIME_GITHUB_INSTALLATION_ID`, `MINIME_GITHUB_PRIVATE_KEY_PATH`) is missing or invalid:
  - Adapter operations fail immediately with `GitHubAuthorizationError` or structured `UNOBSERVABLE`/`NOT_READY` reasons.
  - No fallback to `gh` CLI or operator user tokens is ever attempted.
- Presence of an active personal `gh` CLI session on the host machine does not alter runtime behavior or grant ambient authority.

## Risks / Trade-offs

- **[Risk] GitHub API rate limiting or temporary network outage during readiness or orchestration.**
  → **Mitigation:** Adapter returns `UNOBSERVABLE` lookup state, allowing orchestration to stop cleanly in `WAITING_EXTERNAL` without state corruption or duplicate PR creation.
- **[Risk] Clock skew between local host and GitHub API servers causing JWT validation failure.**
  → **Mitigation:** Backdate JWT `iat` by 60 seconds (`now - 60s`) and set `exp` to `now + 540s` (9 minutes), providing resilience against local clock drift.
- **[Risk] Subprocess failure diagnostics leaking authorization headers.**
  → **Mitigation:** Wrap subprocess execution in `GitHubAdapter` with explicit redaction that strips any authorization header patterns before constructing exception messages or log events.
- **[Risk] Ephemeral token expiration during an ongoing operation.**
  → **Mitigation:** Token lifetime is 1 hour; the adapter proactively refreshes any token with less than 60 seconds of validity before initiating API calls or Git operations.

## Migration Plan

1. Implement `GitHubAppAuth` and direct REST API client in `src/minime/adapters/github.py`.
2. Update `ReadinessService` to execute remote Issue verification.
3. Update unit and integration test doubles to simulate GitHub App installation responses and test error boundaries.
4. Verify full regression test suite without modifying historical migrations 001–008.

## Open Questions

None that alter specifications or task decomposition. Host environment variables (`MINIME_GITHUB_APP_ID`, `MINIME_GITHUB_INSTALLATION_ID`, `MINIME_GITHUB_PRIVATE_KEY_PATH`) already exist and define the installation context.
