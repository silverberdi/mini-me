## 1. GitHub App Authentication & Ephemeral Token Management

- [x] 1.1 Implement RS256 JWT generation using configured App ID, private key path, clock drift tolerance (`iat = now - 60s`), and expiration (`exp = now + 540s`).
- [x] 1.2 Implement installation access token exchange via `httpx` calling `POST /app/installations/{installation_id}/access_tokens`.
- [x] 1.3 Implement volatile in-memory token caching with proactive refresh when remaining token lifetime is below 60 seconds.
- [x] 1.4 Implement strict fail-closed error handling and exception models when App credentials or private keys are missing, invalid, or unauthorized.
- [x] 1.5 Add unit tests for JWT generation, token retrieval, caching, automatic refresh, error handling, and zero token persistence to disk/logs.

## 2. Canonical GitHub REST API Client in GitHubAdapter

- [x] 2.1 Refactor `GitHubAdapter` to use direct HTTP REST API calls via `httpx` authenticated under the GitHub App installation token, replacing `gh` CLI subprocess invocations.
- [x] 2.2 Implement repository identity and access verification (`GET /repos/{owner}/{repo}`).
- [x] 2.3 Implement remote Issue existence and repository ownership verification (`GET /repos/{owner}/{repo}/issues/{issue_number}`).
- [x] 2.4 Implement authoritative PR lookup (`GET /repos/{owner}/{repo}/pulls`) preserving `NOT_FOUND`, `FOUND_EXACT`, `UNOBSERVABLE`, and `AMBIGUOUS` states.
- [x] 2.5 Implement PR creation (`POST /repos/{owner}/{repo}/pulls`) under App identity verifying returned head SHA equality.
- [x] 2.6 Add adapter tests for REST operations, PR lookup states, ambiguous responses, and rate limit / network unobservability.

## 3. Ephemeral Git Push & Remote Reference Authorization

- [x] 3.1 Implement ephemeral Git push authentication using `git -c http.extraHeader` authorization headers bound to registered repository and exact candidate SHA.
- [x] 3.2 Implement remote branch reference queries (`get_remote_branch_head`) with ephemeral authentication.
- [x] 3.3 Add command sanitization and secret redaction ensuring authorization headers and tokens never appear in exceptions, logs, or diagnostics.
- [x] 3.4 Add tests verifying Git push executes with exact candidate SHA, enforces repository root protections, and leaves no tokens in `.git/config` or persistent remotes.

## 4. Readiness Service Remote Issue Validation

- [x] 4.1 Update `ReadinessService.evaluate_change_readiness` to execute remote Issue existence and repository ownership checks through `GitHubAdapter`.
- [x] 4.2 Ensure transient remote unobservability during readiness evaluation produces distinguishable transient reasons rather than permanent binding contradictions.
- [x] 4.3 Add readiness tests covering existing remote issue, nonexistent issue (404), repository mismatch, and unobservable GitHub API.

## 5. Verification, Security Auditing, & Acceptance

- [x] 5.1 Add tests proving personal `gh` CLI authentication does not alter runtime authority and is never used as fallback.
- [x] 5.2 Validate all acceptance scenarios A through J against unit and isolated boundary test suites.
- [x] 5.3 Audit log and event outputs across test runs to verify absolute zero persistence of installation tokens or private key material.
- [x] 5.4 Run the complete 001–008 regression test suite to ensure existing behavior and contracts remain intact.
