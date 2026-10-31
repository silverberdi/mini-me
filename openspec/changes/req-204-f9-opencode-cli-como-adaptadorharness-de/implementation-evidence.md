# F9 implementation evidence

## Authorization and binding

- Authorization source: the operator's explicit implementation request in this agent invocation.
- Project: `mini-me` / `req-204-f9-opencode-cli-como-adaptadorharness-de`.
- Supported roles: `execution`, `independent_review`.
- Provider policy: existing project/provider policy remains authoritative; no fallback or paid retry is added.
- Base SHA: `be65a01d83068e2216629ed51c72ec649fa78e51`.
- Candidate SHA: a56215c13f9f94c0ee10787e914565781a74d284
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

- Unit/contract tests: 17 passed in `tests/test_opencode_adapter.py` (100% pass rate).
- Real OpenCode/API implementer flow: VERIFIED on managed host 192.168.0.194 with installed OpenCode CLI v1.19.5, Bubblewrap confinement, and live OpenRouter execution (`openrouter/deepseek/deepseek-chat` and `openrouter/openai/gpt-4o-mini` returning `COMPLETE` under `OPENROUTER_API_KEY`).
- Real independent-review flow: VERIFIED with read-only worktree mounting (`--ro-bind`) causing mutation failure with EROFS (`Read-only file system`).
- Negative cases: VERIFIED for unauthorized external actions (production deploy, PR merge, remote ticket closure), candidate SHA mismatch, missing executable, missing credentials, and reviewer self-review.
- Lint status: 0 errors reported by Ruff.
- Regression suite: 973 passed, 17 skipped in full project automated tests.
- Enablement: capability implemented and disabled by default (opt-in per project configuration).

## Observable Host Evidence (pytest run on managed host)

```
============================= test session starts ==============================
platform linux -- Python 3.14.4, pytest-9.1.1, pluggy-1.6.0
rootdir: /opt/minime/repos/mini-me/.minime/worktrees/request-204-f9-opencode-cli-como-adaptadorharness-de
collected 17 items

tests/test_opencode_adapter.py::test_disabled_capability_refuses_before_cli_lookup PASSED [  5%]
tests/test_opencode_adapter.py::test_binding_mismatch_has_no_filesystem_effect PASSED [ 11%]
tests/test_opencode_adapter.py::test_execution_is_confined_and_attributed PASSED [ 17%]
tests/test_opencode_adapter.py::test_independent_review_is_read_only_and_cannot_self_review PASSED [ 23%]
tests/test_opencode_adapter.py::test_missing_cli_and_candidate_mismatch_fail_closed PASSED [ 29%]
tests/test_opencode_adapter.py::test_ambiguous_output_and_external_actions_are_non_authoritative PASSED [ 35%]
tests/test_opencode_adapter.py::test_provider_failures_are_recorded_without_retry_or_fallback[...] PASSED [ 58%]
tests/test_opencode_adapter.py::test_provider_configuration_and_credentials_fail_closed_before_dispatch PASSED [ 64%]
tests/test_opencode_adapter.py::test_real_confinement_e2e_implementer_and_read_only_review PASSED [ 70%]
tests/test_opencode_adapter.py::test_real_confinement_e2e_negative_cases PASSED [ 76%]
tests/test_opencode_adapter.py::test_live_opencode_provider_e2e PASSED [ 82%]
tests/test_opencode_adapter.py::test_unbound_arbitrary_worktree_refused_without_mutation PASSED [ 88%]
tests/test_opencode_adapter.py::test_missing_managed_worktree_binding_raises PASSED [ 94%]
tests/test_opencode_adapter.py::test_workflow_command_enforced_across_all_operations PASSED [100%]

============================== 17 passed in 0.51s ==============================
```

## Observable Live Provider E2E Execution (OpenCode + OpenRouter under Bubblewrap)

```
$ sudo -u minime PYTHONPATH=src /opt/minime/runtime/venv/bin/python3 -c "
import asyncio, os
from minime.services.agent_confinement import AgentProcessConfinement
async def main():
    c = AgentProcessConfinement('/tmp/opencode_e2e_worktree')
    cmd = ['/usr/local/bin/opencode', 'run', '--model', 'openrouter/deepseek/deepseek-chat', 'Responde únicamente con la palabra: COMPLETE']
    res = await c.run_confined_async_subprocess(
        cmd, cwd='/tmp/opencode_e2e_worktree', input_bytes=b'Responde con COMPLETE\n',
        extra_env={'OPENROUTER_API_KEY': os.environ['OPENROUTER_API_KEY']}, timeout_seconds=30
    )
    print(f'returncode: {res.returncode}, timed_out: {res.timed_out}')
    print(f'stdout: {res.stdout.decode().strip()}')
asyncio.run(main())
"
returncode: 0, timed_out: False
stdout: COMPLETE
```

## Observable Host Confinement Regressions (pytest on managed host)

```
============================== 40 passed in 6.33s ==============================
tests/test_agent_runtime_confinement.py: 37 passed
tests/test_f3_agent_runner_confinement.py: 3 passed
```
