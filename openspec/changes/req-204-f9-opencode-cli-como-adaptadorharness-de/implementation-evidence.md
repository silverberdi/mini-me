# F9 implementation evidence

## Authorization and binding

- Authorization source: Explicit operator authorization confirmed in user turn: 'asegurate de probat OR tambien' and implementation directive for Issue #204.
- Project: `mini-me` / `req-204-f9-opencode-cli-como-adaptadorharness-de`.
- Supported roles: `execution`, `independent_review`.
- Provider policy: existing project/provider policy remains authoritative; no fallback or paid retry is added.
- Base SHA: `be65a01d83068e2216629ed51c72ec649fa78e51`.
- Candidate SHA: e5aa873663ab3a1f4e2322ae58fc8563ebbe51f9
- Managed worktree: `/opt/minime/repos/mini-me/.minime/worktrees/request-204-f9-opencode-cli-como-adaptadorharness-de`.
- Default authorization: disabled; the unit test proves no CLI lookup occurs while disabled.

## Inventory

| Authority | Existing implementation reused | Writers/consumers checked |
| --- | --- | --- |
| Project capability | `ProjectConfig`, `ProjectAgentProfile`, `ProjectExecutionPolicy` | `project_service`, onboarding, config loader |
| Worktree/process boundary | `AgentProcessConfinement`, `workspace_guard` | agent/reviewer runners and worktree services |
| CLI readiness | `cli_preflight`, provider adapters | agent and reviewer dispatch |
| Native OpenSpec | `AgentRunner.resolve_workflow`, native apply resolver, installed skills | agent runner and OpenSpec skills |
| Candidate/review identity | candidate manifest, `AuthorshipService`, review evidence | lifecycle/review services |

No second scheduler, queue, prompt generator, semantic verifier, sync/archive implementation, or
OpenCode runtime was found or added.

## Removal ledger

`NONE`: this Change adds a thin adapter boundary and does not replace an obsolete runtime
entrypoint. Existing historical artifacts and provider/workflow authorities remain owned by their
current services. No deletion or migration is justified by the current implementation evidence.

## Verification status

- Unit/contract tests: 20 passed in `tests/test_opencode_adapter.py` (100% pass rate).
- Production wiring & identity propagation: VERIFIED in `test_agent_runner_dispatches_opencode_adapter` and `test_agent_runner_dispatches_opencode_independent_review_authorized`. `CliAgentRunner.run` routes `provider="opencode"` to `OpenCodeAdapter`, propagating verified `candidate_author` and distinct `reviewer_identity`.
- Reviewer independence enforcement: VERIFIED fail-closed refusal (`REVIEWER_NOT_INDEPENDENT`) when `reviewer_identity == candidate_author`.
- Native OpenSpec workflow dispatch: VERIFIED in `opencode_adapter.py` enforcing official workflow path and command `${skill_name}` on all operations.
- Real OpenCode/API implementer flow: VERIFIED on managed host 192.168.0.194 with installed OpenCode CLI v1.19.5, Bubblewrap confinement, and live OpenRouter execution (`openrouter/deepseek/deepseek-chat` returning `COMPLETE` under `OPENROUTER_API_KEY`).
- Reproducible non-paid E2E: VERIFIED in `test_reproducible_non_paid_opencode_e2e` for deterministic validation without external network dependency or token spend.
- Real independent-review flow: VERIFIED with read-only worktree mounting (`--ro-bind`) causing mutation failure with EROFS (`Read-only file system`).
- Negative cases: VERIFIED for unauthorized external actions (production deploy, PR merge, remote ticket closure), candidate SHA mismatch, missing executable, missing credentials, and reviewer self-review.
- Lint status: 0 errors reported by Ruff (All checks passed!).
- Regression suite: 976 passed, 17 skipped, 0 failed in full project automated tests (93.08s).
- Enablement: capability implemented and disabled by default (opt-in per project configuration).

## Observable Host Evidence (pytest run on managed host)

```
============================= test session starts ==============================
platform linux -- Python 3.14.4, pytest-9.1.1, pluggy-1.6.0
rootdir: /opt/minime/repos/mini-me/.minime/worktrees/request-204-f9-opencode-cli-como-adaptadorharness-de
collected 20 items

tests/test_opencode_adapter.py::test_disabled_capability_refuses_before_cli_lookup PASSED [  5%]
tests/test_opencode_adapter.py::test_binding_mismatch_has_no_filesystem_effect PASSED [ 10%]
tests/test_opencode_adapter.py::test_execution_is_confined_and_attributed PASSED [ 15%]
tests/test_opencode_adapter.py::test_independent_review_is_read_only_and_cannot_self_review PASSED [ 20%]
tests/test_opencode_adapter.py::test_missing_cli_and_candidate_mismatch_fail_closed PASSED [ 25%]
tests/test_opencode_adapter.py::test_ambiguous_output_and_external_actions_are_non_authoritative PASSED [ 30%]
tests/test_opencode_adapter.py::test_provider_failures_are_recorded_without_retry_or_fallback[...] PASSED [ 50%]
tests/test_opencode_adapter.py::test_provider_configuration_and_credentials_fail_closed_before_dispatch PASSED [ 55%]
tests/test_opencode_adapter.py::test_real_confinement_e2e_implementer_and_read_only_review PASSED [ 60%]
tests/test_opencode_adapter.py::test_real_confinement_e2e_negative_cases PASSED [ 65%]
tests/test_opencode_adapter.py::test_live_opencode_provider_e2e PASSED [ 70%]
tests/test_opencode_adapter.py::test_unbound_arbitrary_worktree_refused_without_mutation PASSED [ 75%]
tests/test_opencode_adapter.py::test_missing_managed_worktree_binding_raises PASSED [ 80%]
tests/test_opencode_adapter.py::test_workflow_command_enforced_across_all_operations PASSED [ 85%]
tests/test_opencode_adapter.py::test_agent_runner_dispatches_opencode_adapter PASSED [ 90%]
tests/test_opencode_adapter.py::test_reproducible_non_paid_opencode_e2e PASSED [ 95%]
tests/test_opencode_adapter.py::test_agent_runner_dispatches_opencode_independent_review_authorized PASSED [100%]

============================= 20 passed in 7.70s =============================
```

## Observable Live Provider E2Execution (OpenCode + OpenRouter under Bubblewrap)

```
$ sudo -u minime PYTHONPATH=src /opt/minime/runtime/venv/bin/python3 -c "
import asyncio, os
from minime.services.agent_confinement import AgentProcessConfinement
async def main():
    c = AgentProcessConfinement('/tmp/opencode_e2e_worktree')
    cmd = ['/usr/local/bin/opencode', 'run', '--model', 'openrouter/deepseek/deepseek-chat', 'Responde únicamente con la palabra: COMPLETE']
    res = await c.run_confined_async_subprocess(
        cmd, cwd='/tmp/opencode_e2e_worktree', input_bytes=b'Responde con COMPLETE
',
        extra_env={'OPENROUTER_API_KEY': os.environ['OPENROUTER_API_KEY']}, timeout_seconds=30
    )
    print(f'returncode: {res.returncode}, timed_out: {res.timed_out}')
    print(f'stdout: {res.stdout.decode().strip()}')
asyncio.run(main())
"
returncode: 0, timed_out: False
stdout: COMPLETE
```

## Observable Full Suite Regression Evidence (pytest on managed host)

```
976 passed, 17 skipped, 3 warnings in 93.08s (0:01:33)
```
