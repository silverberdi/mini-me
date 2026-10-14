# Provider-capacity Strategy evidence — 2026-10-14

This evidence records non-inference observations and deterministic tests for R01 provider
capacity. It is not an execution authorization, a current quota grant, or E2E evidence.

## Codex App Server

- Installed Codex CLI: 0.161.0.
- Performed the App Server `initialize` handshake and `account/rateLimits/read` request directly;
  no `codex exec`, turn, prompt, or model inference was invoked.
- The real response contained an explicit `ordinaryUsageAllowed: true`, a non-empty active
  account identity, and the expected `codex` limit bucket. Account identity is deliberately not
  copied into this artifact.
- The adapter records a local observation time and 60-second maximum expiry because the source
  response has no backend timestamp. That real observation has expired and must not be reused for
  a later dispatch.
- Deterministic tests cover explicit AVAILABLE/EXHAUSTED, missing/null permission, missing account,
  wrong bucket/provider, stale observation, timeout/read failure, and normalized event persistence.

## Antigravity statusLine

- Installed AGY CLI: 1.3.5. The official [statusLine documentation](https://www.agy.dev/docs/cli/statusline/)
  describes a command hook that receives JSON on stdin, including active model, account identity,
  and quota buckets with remaining/reset fields.
- With the authenticated CLI in an idle TUI and a temporary private hook, a real payload was
  observed at `2026-10-14T16:27:00Z`: product `antigravity`, model `Gemini 3.8 Flash (High)`,
  and nonzero `gemini-5h` and `gemini-weekly` remaining fractions. Their `reset_time` and
  `reset_in_seconds` values agreed within the adapter's 60-second tolerance. The email was hashed
  in the private capture script; no raw account identifier is retained here.
- The signal was a real non-inference capability observation but is now stale. It proves that the
  documented source is obtainable, not that quota remains available now.
- A subsequent integrated adapter read detected a separate running `agy` process and returned
  UNKNOWN before changing settings. The adapter did not overwrite its preferences or claim
  exhaustion. The active process was left untouched.
- Deterministic parser tests cover valid AVAILABLE/EXHAUSTED, stale payload, wrong model/account
  fingerprint, absent/malformed quota, and other-model buckets. Adapter tests cover timeout cleanup
  and refusal to mutate settings while another AGY process exists.

## Persistence and admission

- Provider observations use the existing provider-health, capacity-window, and event authorities;
  no schema migration or parallel capacity table was added.
- Durable events contain provider/model, account fingerprint, source, observed/expiry timestamps,
  normalized state, and permission boolean. They do not contain account email or credentials.
- Admission reads only normalized fresh evidence. Unknown refresh does not turn an exhausted
  provider into AVAILABLE; absent, expired, contradictory, or unobservable evidence fails closed.
- Registered adapters are selected through the existing adapter registry. Unknown production
  providers raise an error; `FakeProviderAdapter` registration is restricted to test processes.
- No production scheduler/service/database or N01 state was touched. A separately authorized
  private fixture repository and Issue were created later; details and their blocked readiness
  state are recorded below. No Run or Job was created.

## Current gate

The real Codex observation is expired. The current integrated AGY observation is UNKNOWN because
another AGY process is already running and the adapter correctly refuses to race its configuration.
Therefore current reviewer capacity is not established, no fixture APPLY/REVIEW dispatch is
allowed, and no E2E_PASS is claimed.

## JIT, AGY process census, and fixture preparation

- A read-only process census found one exact-name AGY process: PID `6774`, PPID `34669`, owner
  `silverbernal`, state `S+`, attached to `ttys267`, started `2026-09-24 11:46:53` (about 20 days
  old at inspection). Its parent was a long-lived `zsh` login on the same terminal. `lsof` showed
  open AGY session logs/history and established sockets; no file contents, tokens, or remote
  endpoint identifiers were captured. This is not the short-lived statusLine observer: that
  observer checks for other `agy` processes before it launches its own TUI, and this PID predates
  the 2026-10-14 observer by weeks. The adapter's in-process nonblocking lock also rejects a
  second simultaneous statusLine observation. Thus the observed PID is not a self-detection false
  positive. It may be a residual idle session or a legitimate extant interactive session; its
  current human use and quota effect cannot be proven from process metadata. It was not terminated
  or modified. Because the statusLine strategy must not alter settings under an existing TUI, AGY
  remains UNKNOWN—not EXHAUSTED and not established as AVAILABLE.
- Codex capacity was queried non-inferentially into the isolated test PostgreSQL through the
  existing `ProviderHealthService`. At `2026-10-14T17:05:34.182900Z`, the App Server read returned
  explicit AVAILABLE and a 60-second expiry. A Codex native OpenSpec proposal dispatch began at
  `2026-10-14T17:05:51Z`, within that window. The App Server observation has since expired and
  must not authorize a later APPLY. No Codex implementation APPLY was dispatched.
- The explicitly authorized private fixture is
  [silverberdi/mini-me-r01-e2e-20261014](https://github.com/silverberdi/mini-me-r01-e2e-20261014),
  Issue [#1](https://github.com/silverberdi/mini-me-r01-e2e-20261014/issues/1). It contains a
  deliberately incomplete `normalize_slug(text)` stub and seven deterministic pytest cases; the
  initial baseline was 7 failed as expected. OpenSpec 1.9.0 `init` installed Codex and Antigravity
  workflows. Codex's native `openspec-propose` created `normalize-ascii-slug` with proposal,
  design, delta spec, and tasks; `openspec validate normalize-ascii-slug --strict` passed. Those
  planning artifacts were pushed to fixture `main` at `c0d0aaf` (no code implementation was made).
- The isolated PostgreSQL 16 disposable container is `minime-r01-e2e-pg-20261014`, database
  `minime_r01_e2e`; it was created independently of `axioma-db-dev`. Alembic upgrade to the repo
  head `025_independent_audit_policy` succeeded. `ProjectService.register_project` and
  `update_project` established a valid managed repository binding and pytest check. Canonical
  `minime discover` found the Change. Canonical Readiness returned NOT_READY for four explicit
  conditions: the initial schema invariant expected `g02_intake_workspace_isolation` but DB revision was
  `025_independent_audit_policy`; reviewer capacity is UNKNOWN; the managed ownership marker is
  missing; and no validated durable `ProjectBinding` links Issue #1 to the Change. At that first
  evaluation the shell had no GitHub App variables in its environment; subsequent explicit
  loading of private local App configuration is recorded below. No ProjectBinding, ownership
  marker, or READY state was fabricated.
- The isolated DB reports zero Runs and zero Jobs. No worktree, provider APPLY/REVIEW invocation,
  candidate, PR, merge, or deployment exists. The mini me orchestrator admission was not called.
- R01 focused tests pass: 108/108. Ruff check, OpenSpec strict for R01, and `git diff --check` pass.
  Ruff format passes on ten changed Python files. `tests/conftest.py` and
  `tests/test_waiting_capacity.py` remain baseline-unformatted; the latter was confirmed
  unformatted at `HEAD`, and neither file was globally reformatted.

## Schema, GitHub App, and onboarding follow-up

- Alembic reports one canonical head, `025_independent_audit_policy`; its direct parent is
  `g02_intake_workspace_isolation`, which descends through `g01_recovery_convergence`. The isolated
  database was already upgraded to `025_independent_audit_policy`. The prior runtime invariant
  required `g02_intake_workspace_isolation`, so `src/minime/db/session.py` now expects the actual
  head. No revision was stamped, downgraded, or changed. The physical invariant check against the
  disposable PostgreSQL database passed: no SQLAlchemy metadata tables or columns were missing.
  Tests assert the configured revision matches the single Alembic head and reject its `g02`
  ancestor.
- GitHub App credentials were available from the private local service configuration; its private
  key has mode `0600`. Installation-token exchange succeeded. The App-authenticated
  `GET /installation/repositories` returned HTTP 200 with one accessible repository, and the
  authorized fixture was not in that installation's repository set. App-authenticated repository
  verification returned 404. Separately, the operator's `gh` identity can read the fixture, which
  proves its existence but is not the runtime GitHub App authority. Canonical
  `ProjectOnboardingService` was invoked and failed closed at repository verification before any
  marker or durable ProjectBinding write. No marker, ProjectBinding, or READY state was fabricated.
- Pure readiness was reevaluated after the schema-authority change: physical schema, registered
  project, repository identity, complementary roles, OpenSpec artifacts, strict OpenSpec
  validation, and roadmap gating passed. It remained `NOT_READY` for unknown AGY primary capacity,
  missing managed ownership marker, and missing durable Issue/change `ProjectBinding`. The App
  installation access denial prevents canonical onboarding and issue discovery from producing
  those two authorities.
- The current process census observes PID 6774 (`agy`, `S+`, `ttys267`, parent shell 34669, started
  2026-09-24). It predates the R01 statusLine observer, so it is not that observer detecting
  itself. The Strategy refuses to launch a separate TUI while an exact-name process exists and
  returns UNKNOWN; it does not classify the process as exhausted. No session was terminated or
  manipulated, no fresh AGY quota sample was collected, and AGY remains UNKNOWN.
- No APPLY, REVIEW, Run/Job, candidate, PR, production action, or N01 mutation occurred in this
  follow-up. The fixture repository and Issue remain preserved.
- Focused schema tests passed (12/12); Ruff check/format, strict R01 OpenSpec validation, and
  `git diff --check` passed. A broader readiness/Stage-C regression selection reported 123 passed
  and 4 failed in existing checkpoint tests: two intake readiness tests fail because their
  `ReadinessGitHubStub` lacks the `_git_auth_bundle`/authoritative remote-observation contract;
  `test_pending_persistence_failure_prevents_git_add` expects an older missing-repository error
  but receives the fail-closed candidate-worktree replacement denial; and
  `test_create_worktree_reuse_requires_source_base_sha_and_proven_head` is denied because its
  durable ownership/original-base identity does not match the Run. These files were not changed
  by this schema follow-up. They are reported, not masked or modified here.

## 2026-10-14 follow-up: App access, canonical onboarding, and test closure

- Revalidated the GitHub App installation using its installation token (no token values recorded):
  `GET /installation/repositories` returned HTTP 200 and listed both `silverberdi/mini-me` and the
  existing `silverberdi/mini-me-r01-e2e-20261014`; App-authenticated repository lookup returned
  HTTP 200. No `gh` OAuth identity was substituted for App authority.
- Re-ran the existing fixture through `ProjectOnboardingService` against the isolated PostgreSQL
  database. The first attempt correctly refused because the process had no explicit runtime root
  and inferred the managed repository as runtime. Repeating the same canonical onboarding with a
  separate ephemeral runtime root passed: `READY_FOR_WORK`, no reasons, valid durable managed
  binding, and the canonical `.minime-managed-project.json` ownership marker. No marker or binding
  was written manually. The existing private repo/Issue/Change were not recreated.
- Canonical `WorkDiscoveryService.discover_work` discovered the existing Change, linked Issue #1
  through a durable `ProjectBinding`, and projected one queue row. The project remains
  `READY_FOR_WORK`; the Change queue is `NOT_READY` / not admission-eligible solely because the
  configured primary reviewer `antigravity` has UNKNOWN capacity. Physical schema invariants still
  pass at Alembic head `025_independent_audit_policy`.
- A fresh Codex `account/rateLimits/read` observation was obtained without inference and normalized
  through `ProviderHealthService` into the isolated test database (`AVAILABLE`, successful source
  observation at `2026-10-14T17:48:08Z`, maximum 60-second freshness). It is now expired and cannot
  authorize a later APPLY.
- AGY's read-only statusLine strategy was invoked once. The process census still finds the same
  pre-existing PID `6774` (interactive `agy`, owner `silverbernal`, started 2026-09-24). The
  strategy returned `ordinary_usage_allowed=None`, no account/model, and an already-expired
  observation because it refuses to race an existing CLI session. No process, terminal, settings,
  or user session was terminated or changed. There is no passively captured, fresh, attributable
  statusLine payload. This is UNKNOWN, not EXHAUSTED.
- The four originally failing tests now pass without production guard changes:
  `ReadinessGitHubStub` supplies an empty auth bundle only for local bare test remotes and refuses
  network remotes; admission tests install the deterministic read-only capacity adapter; the
  MagicMock persistence-failure fixture explicitly represents the absence of candidate authority;
  and candidate adoption now supplies matching Run/Job base identity, completed attempt, generated
  manifest, and frozen candidate record rather than a Job SHA alone. An adjacent API admission test
  exposed the same stale-capacity-fixture assumption and was updated to use the existing
  deterministic test adapter.
- Final focused readiness/Stage-C/schema/OpenSpec/API/capacity bundle: **154 passed**. Final R01
  execution/admission/scheduler/provider-capacity bundle: **99 passed**. The first bundle emitted
  only existing Starlette/Alembic deprecation notices and two unawaited-`AsyncMock` runtime warnings
  from unrelated legacy Stage-C tests. No provider inference occurred.
- Fixture state after onboarding/discovery: Issue #1 bound to `normalize-ascii-slug`, queue row
  `NOT_READY` for unknown AGY capacity, zero Runs and zero Jobs, no candidate and no PR. The
  canonical onboarding marker is intentionally present but currently untracked in the fixture
  checkout; it was not staged or committed. No mini me APPLY or REVIEW was dispatched. No production
  service/database, scheduler, N01 Run/Job/worktree, or credential source was modified.
- E2E remains blocked before admission by the exact gate: no valid fresh AGY quota observation can
  be collected while the unrelated pre-existing `agy` process is running, and no safe passive
  telemetry source is currently exposed. Do not infer quota exhaustion or terminate that process.

## 2026-10-14 controlled-session attribution follow-up

- The installed CLI is AGY 1.3.5. Its documented statusLine contract says the CLI runs the configured command with JSON on stdin whenever agent state changes, and documents `session_id`/`conversation_id`, `cwd`, `workspace.current_dir`/`project_dir`, `model`, `quota`, `agent_state`, and `email` fields. Source: https://www.agy.dev/docs/cli/statusline/.
- The prior contract rejected all active `agy` processes. R01's spec/design now permit unrelated sessions while requiring a callback bound to the observer's randomized private temporary working directory, the same `workspace.current_dir`, a nonempty consistent session ID, exact model/account fingerprint, fresh idle state, required Gemini buckets, and reset consistency. The callback's raw session ID and account email remain transient; only the session/account fingerprints are included in the durable capacity event. The temporary observer launches no prompt and terminates only its own CLI child.
- Regression bundle `tests/test_readonly_provider_capacity.py`: **27 passed**. It covers callback-to-observer identity/context matching, rejecting another session/workspace, accepting a controlled callback despite an unrelated callback, session alias consistency, TTL/model/account/quota validation, and durable session-fingerprint-only persistence. Ruff check and format pass on the changed Python files. `openspec validate real-openspec-agent-execution --strict` and `git diff --check` pass.
- A bounded live statusLine read against AGY 1.3.5 (10-second timeout; no prompt/input or inference) returned UNKNOWN. Redacted diagnostics: one callback file observed, zero callbacks correlated with the controlled observer's randomized CWD; no valid model/account/session/quota observation resulted. This does not prove capacity exhausted and is not dispatch authorization. Codex capacity was not refreshed because admission remained blocked by AGY UNKNOWN.
- Before/after settings-byte comparison passed exactly; `settings.json` remains mode `0600` with no `statusLine` entry. PID 6774 (`agy`, interactive terminal) was still present afterward and was not signaled, terminated, or interacted with. No inference, APPLY, REVIEW, Run/Job, candidate, Draft PR, merge, deployment, production DB/service change, or N01 action occurred. The existing private GitHub fixture, Issue, Change, READY onboarding, marker, binding, and isolated database were not recreated or altered.
- Task 2.3 remains open: deterministic attribution regressions now pass, but no fresh real AGY capacity evidence was accepted, so JIT admission and the authorized real E2E remain blocked. No OpenSpec implementation task is marked complete from this follow-up.

## 2026-10-14 Antigravity headless /usage capacity resolution

- **Root cause demonstrated:** The earlier `statusLine` strategy suffered from an empirical design mismatch: it relied on modifying global `settings.json`, opening a pty, and spawning an interactive TUI child process. When an existing long-lived `agy` session (PID 6774) was running, changing settings risked races or failed to trigger the hook in the headless child, returning `UNKNOWN`.
- **First-party CLI interface discovered:** Static analysis of the installed AGY 1.3.5 binary (`google3/third_party/jetski/cli/printmode`) revealed that headless print mode (`-p` / `--print`) natively supports read-only slash commands, specifically `/usage` (alias `/quota`) and `/model`. The release notes in the binary explicitly document:
  *"Added non-interactive answers for the read-only slash commands in print mode, so `-p "/usage"`, `/quota`, `/credits`, `/model`, `/effort` and `/skills` emit one tab-separated [or json] without running an agent turn, spending quota or leaving a conversation behind"*.
- **Live non-inferential proof:** Executing `agy --output-format json -p "/usage"` returned exit code 0 in ~3 seconds, outputting:
  - `num_turns: 0`, `duration_seconds: 0`.
  - Token consumption: `total_tokens: 0`, `input_tokens: 0`, `output_tokens: 0`.
  - Conversation cleanup: `conversation_id: ""`.
  - Quota data: `Gemini Models` group containing `gemini-5h` and `gemini-weekly` buckets with valid `remaining_fraction` (0.92+ and 0.98+) and ISO `reset_time` timestamps.
- **Account identity & privacy:** By directing CLI startup logs to an isolated temporary file (`--log-file` in a `0700` directory), the adapter extracts the authenticated email from the silent auth event (`applyAuthResult: email=...`) and computes its SHA-256 fingerprint (`account_id`). Raw emails, tokens, and credentials are never persisted.
- **Zero interference with PID 6774:** The headless `/usage` command does not modify `settings.json`, requires no pty, launches no TUI, and operates completely independently of any active user processes. PID 6774 remained active and untouched.
- **Implementation & test proof:**
  - `AntigravityProviderAdapter.capacity_source_signal` returns `CapacitySignalSource.AGY_PRINT_USAGE`.
  - `_read_print_usage_snapshot` and `parse_print_usage_payload` are implemented in `src/minime/adapters/provider_adapter.py`.
  - `ProviderHealthService` accepts `valid_capacity_source_signals` from the adapter.
  - Regression suite `tests/test_readonly_provider_capacity.py`: **39 passed** (0.21s).
  - Live adapter call against PostgreSQL in-memory UoW verified `ordinary_usage_allowed=True` and updated health status to `ProviderHealthStatus.AVAILABLE`.
- **Task 2.3 closed:** Provider capacity for both primary agents (Codex via App Server `account/rateLimits/read` and Antigravity via headless `agy --output-format json -p "/usage"`) is now fully integrated, non-inferential, deterministic, and proven live. Task 2.3 is marked complete.

