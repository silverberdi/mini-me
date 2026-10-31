# F9 implementation evidence

## Authorization and binding

- Authorization source: the operator's explicit implementation request in this agent invocation.
- Project: `mini-me` / `req-204-f9-opencode-cli-como-adaptadorharness-de`.
- Supported roles: `execution`, `independent_review`.
- Provider policy: existing project/provider policy remains authoritative; no fallback or paid retry is added.
- Base SHA: `be65a01d83068e2216629ed51c72ec649fa78e51`.
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

- Unit/contract tests: 14 passed in `tests/test_opencode_adapter.py`.
- Real OpenCode/API implementer flow: VERIFIED with installed OpenCode CLI v1.19.5, Bubblewrap confinement, and live DeepSeek execution.
- Real independent-review flow: VERIFIED with read-only worktree mounting (--ro-bind) and failure on write attempt.
- Enablement: capability implemented and disabled by default (opt-in per project configuration).
