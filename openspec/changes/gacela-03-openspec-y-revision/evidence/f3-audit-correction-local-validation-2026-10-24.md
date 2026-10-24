# F3 audit correction — local validation (2026-10-24)

## Implemented controls

- CLI and REST construct `CliAgentRunner` only from persisted F2 profiles, live CLI resolution, the capacity service, and the budget service. Missing profiles or managed bindings fail closed.
- The REST boundary passes `operator_clarification`; it no longer passes the nonexistent `operator_response` coordinator argument.
- Agent stages require exit code `0`, no timeout/preflight/environment error, and non-empty evidence. Native Propose, Apply, Verify, reviews, Sync, and Archive advance independently only after that check.
- Complexity is requested from the configured thinking agent as a structured JSON verdict with evidence. Keyword classification is not used.
- Review and Verify require one positive `ReviewVerdictPayload`; empty, textual, conflicting, or ambiguous output is rejected.
- Pytest exit code `5`, `no tests ran`, or missing collection/execution evidence is a failure.
- Git commands return typed results and raise a recoverable error on non-zero exit. PR creation, head/base identity, merge state, and Issue closure are re-read through typed GitHub adapter results before state advancement.
- FIFO continuation records the next eligible remote request only after confirmed closure; scheduler ownership is preserved.

## Verification performed

- Focused F3 contracts: `19 passed` across runner, workspace, fail-closed, native lifecycle, API boundary, and continuity tests.
- Full local regression after the classification: `781 passed, 15 skipped`.
- `python -m ruff check` on affected production and test files: PASS.
- `openspec validate gacela-03-openspec-y-revision --strict`: PASS.
- `git diff --check`: PASS.

The two former `test_e2e_isolated_fixture.py` scenarios use GitHub and agent doubles. They are explicitly skipped as non-acceptance evidence; they do not certify F3 E2E completion.

## Remote fixture observation (read-only)

The existing private fixture `silverberdi/mini-me-r01-e2e-20261014` was queried without mutation. `main` was `6c051b87eb9a8f379e9305b62773bf486a7825f5`. Issues #1, #2, #3, #4, and #5 were open. Existing PRs #2 and #4 were open and unmerged, with heads `a9f1599aa6c45eb47a0925fb0f033e01e02f33e0` and `2208e5d683e64bed79bb4110b6fca33e94e517ff`, respectively. No issue, branch, PR, merge, or fixture file was changed by this validation.

The local operator session could read the fixture. No installation-token grant for the F3 service was consumed or exposed here, and no real agent inference was started while the fixture contained unmerged historical candidates. Therefore tasks 6.3, 6.4, and the complete acceptance task remain unverified.

## Confinement correction

`CliAgentRunner.run()` now invokes `AgentProcessConfinement.run_confined_async_subprocess()` for every configured profile. Direct subprocess creation was removed from the runner. The confined result preserves exit code, timeout, credential-rotation status, sanitized stdout/stderr, and fail-closed errors.

Executable regression coverage:

- `tests/test_f3_agent_runner_confinement.py`: authorized Worktree read succeeds, an attempted write outside the Worktree is blocked, and unavailable confinement prevents process start.
- `tests/test_agent_runtime_confinement.py`: existing credential projection, rotation, cleanup, and secret-suppression tests remain green.
- Full regression after the fix: `783 passed, 15 skipped, 2 warnings`.

## Integration gate

The Ubuntu integration host was inspected without changing the operational service. Its healthy
`local-ai-stack-postgres-1` container runs PostgreSQL 16. A separate database
`minime_f3_e2e_20261024` was created for the isolated runtime; the operational database was not
migrated or written.

An isolated checkout of the published F3 SHA was mounted at `/tmp/minime-f3-runtime-20261024`.
Using the service identity `minime` (`HOME=/var/lib/minime`) and the App environment from
`/etc/minime/minime.env`, with operator `GITHUB_TOKEN`/`GH_TOKEN` unset, the published
`GitHubAdapter.verify_connection_permissions` returned `SUCCESS` for both `tickets` and `git_pr`
against `silverberdi/mini-me-r01-e2e-20261014`. No token or key was printed.

The same service identity reported `codex login status` as logged in and `agy models` exposed
`gemini-3.8-flash-medium` (plus the installed catalog). No inference was invoked. The isolated
Ubuntu confinement regression passed `38 passed, 1 warning`; the test now masks known host runtime
roots when exercising the missing-fallback branch, so it remains deterministic while preserving
the production fallback and fail-closed preflight behavior.

The fixture remains unsafe for the two required authentic runs: open Issues #1, #3, and #5 exist,
but historical PRs #2 and #4 remain open and unmerged. Issues #1 and #3 are the corresponding
historical requests, so consuming them would create duplicate work against historical PRs; using
only #5 cannot provide both required low/moderate and high-complexity runs. No fixture issue,
branch, PR, merge, or file was changed. Tasks 6.3, 6.4, and 6.5 therefore remain unverified.

## Runtime-specific regression classification

With the private XDG cache configured, the Ubuntu runtime reached `481 passed, 12 skipped` before
`tests/test_process_safety.py::test_timeout_terminates_process_group_and_child` failed. The
failure is environmental: Bubblewrap uses a PID namespace, so the child PID written by the test
is namespace-local and `os.kill(pid, 0)` from the host test process does not identify that child.
Immediately after the failure, no `spawn_child.py` or `bwrap` process remained on the host. This
does not certify the test as passed, and it remains classified for a namespace-aware test update
outside the four F3 acceptance tasks; no production cleanup behavior was weakened.

The official OpenSpec 1.13.1 CLI was also exercised in disposable directories. It emits the
the six Codex skills under `.agents/skills` while emitting no Antigravity workflow files, despite
advertising the Antigravity tool. F3 now resolves both native workflow locations when present and
fails closed when the official initializer does not materialize them; it never emulates or copies
them. The installation/resolution suite passed `16 passed, 1 warning` before this stricter
capability assertion; after the fail-closed assertion the same suite passed `16 passed, 1
warning`. This official runtime therefore cannot run an Antigravity-backed F3 review until its
native workflows are actually available.

After the native-path correction, the combined confinement/OpenSpec/workflow-focused suite passed
`54 passed, 1 warning`. The Ubuntu regression excluding the two environment-assumption tests
completed `775 passed, 12 skipped, 5 warnings`; Ruff on all affected files passed with
`--no-cache`, and `openspec validate ... --strict` plus `git diff --check` passed.

## OpenSpec configuration correction

The previous `minime` configuration was explicitly incomplete: `profile=custom`,
`delivery=skills`, and workflows omitted `verify` and `continue`. In an isolated XDG
configuration, the official CLI was configured as `profile=custom`, `delivery=both`, with
`propose`, `explore`, `apply`, `update`, `sync`, `archive`, `verify`, and `continue`.

Running only `openspec init --tools antigravity,codex --no-animation` then produced eight Codex
skills and eight native Antigravity commands under `.agents/`, including `opsx-verify.md` and
`opsx-continue.md`. No files were generated manually. The adapter/tests now require this
configuration for a successful dual-provider setup and fail closed for incomplete delivery or
workflow selections. `ProjectCatalogService` now reports `CONFIGURATION_INCOMPLETE` separately
from definitive provider unavailability. Ubuntu focused installation/resolution/catalog tests
passed `19 passed, 1 warning`.

The fixture was re-read without mutation. Historical PRs #2 and #4 remain open and unchanged;
Issues #6 and #7 are now open and have no associated PR, so they are eligible candidates for the
two requested runs. No run, comment, branch, PR, merge, or closure was performed. Authorization
is still required before consuming #6 and #7 as E2E work items.
