## 1. Remote Request Intake and Selection

- [x] 1.1 Extend `GitHubAdapter.list_issues` to support exhaustive multi-page pagination across all open issues without silent omission of older tickets
- [x] 1.2 Implement `RemoteRequestIntakeService` to query remote repository issues, order them ascending by `created_at` (FIFO), and apply deterministic tie-breaking on issue number
- [x] 1.3 Add filtering in `RemoteRequestIntakeService` to exclude issues tagged `disabled` or having explicit formal dependency directives (`depends on #...`), without treating casual mentions as blocking, preserving FIFO priority when unblocked
- [x] 1.4 Enforce the constraint of at most one active Request per project in `RemoteRequestIntakeService` (allowing idle projects with zero active requests) and recognize re-entrant executions without creating duplicate runs
- [x] 1.5 Implement comprehensive unit tests in `tests/test_remote_request_intake.py` verifying FIFO ordering, pagination, exclusion rules, idle states, and single-active-request enforcement

## 2. Git Workspace Isolation and Agent Process Confinement

- [x] 2.1 Enhance `WorktreeManager` to create and track candidate branches named `request-<numero>-<slug-kebab>` from the latest remote reference of the configured base branch under the project's configured managed root
- [x] 2.2 Consolidate agent execution mechanics into `CliAgentRunner` supporting `thinker`, `implementer`, and `reviewer` roles under `AgentProcessConfinement`, integrating dynamic resolution of installed OpenSpec workflows and skills based on configured agent, OpenSpec version, verified profile capabilities, and native prompt transport (reusing F2 `ProjectCatalogService` and `OpenSpecAdapter`); reject empty executors and unverified bindings from CLI and API; launch subprocesses only through `AgentProcessConfinement.run_confined_async_subprocess()` and prove authorized worktree access plus prohibited-path denial
- [x] 2.3 Integrate preflight verification of provider health, quota availability, and budget limits via `CapacityLifecycleService` and `BudgetService` before each agent invocation, failing closed on exit error, timeout, missing evidence, or ambiguous result
- [x] 2.4 Implement tests in `tests/test_workspace_isolation_and_agent_confinement.py` verifying branch creation, managed root sandboxing, and capacity preflight gating

## 3. Native OpenSpec Propose and Validation Loop

- [x] 3.1 Implement OpenSpec Explore orchestration dynamically resolving and dispatching the native Explore workflow (`opsx-explore` or `openspec-explore`) via `CliAgentRunner` for the configured thinking agent in the confined worktree, failing closed on missing workflow, non-zero exit, timeout, preflight error, absent evidence, or ambiguous result, and strictly forbidding static Python mock responses
- [x] 3.2 Implement autonomous ambiguity clarification in Explore and the `HUMAN REQUIRED` protocol for true material ambiguities, preserving verbatim OpenSpec text and Spanish options without simulating human prompts
- [x] 3.3 Implement OpenSpec Propose orchestration dynamically resolving and dispatching the native Propose workflow (`opsx-propose` or `openspec-propose`) via `CliAgentRunner` for the thinking agent, failing closed on non-zero exit, timeout, preflight error, absent evidence, or ambiguous result, generating canonical change artifacts (`proposal.md`, `specs/`, `design.md`, `tasks.md`), strictly forbidding Python template file writes
- [x] 3.4 Implement strict CLI validation executing `openspec validate <change> --strict --no-interactive` with an automatic correction pass by the thinking agent upon validation failure, capturing authentic CLI error outputs
- [x] 3.5 Implement LLM-grounded complexity evaluation (`low`, `moderate`, `high`) recorded by the configured thinking agent upon successful validation based on architectural scope and risk, without simplistic keyword matching, requiring a positive structured and verifiable verdict
- [x] 3.6 Implement independent proposal review for high-complexity changes using a read-only reviewer prompt dispatched to a distinct agent profile and routing actionable defects back to the thinking agent
- [x] 3.7 Implement unit and integration tests in `tests/test_native_propose_lifecycle.py` covering genuine Explore, Propose, CLI Validate loops, agent-grounded complexity assessment, structured proposal review, and fail-closed errors without vacuous mocks

## 4. Native OpenSpec Apply, Test Execution, and Verify

- [x] 4.1 Implement OpenSpec Apply orchestration dynamically resolving and dispatching the native Apply workflow (`opsx-apply` or `openspec-apply-change`) via `CliAgentRunner` for the implementer agent in the candidate worktree (reusing `resolve_native_openspec_apply`), failing closed on unavailable workflow, non-zero exit, timeout, preflight error, absent evidence, or ambiguity and strictly forbidding regex-based synthetic task completions
- [x] 4.2 Enforce mandatory unit and E2E test execution during Apply, verifying that tests pass with exit code 0, at least one test is collected/executed, pytest exit code 5 or no tests never produces PASS, and observable test execution logs are durably recorded before completing Apply
- [x] 4.3 Implement OpenSpec Verify orchestration executed by the same implementer agent (not the thinking agent), explicitly verifying beforehand that the agent has native Verify installed (`opsx-verify` or `openspec-verify-change`) and failing closed if missing, non-zero, timeout, preflight error, absent evidence, or ambiguous result, without stubbing out verify checks
- [x] 4.4 Implement Verify failure feedback loop delivering the authentic findings report to the implementer in an Apply correction prompt
- [x] 4.5 Implement post-Verify complexity routing: transition low/moderate complexity to `READY FOR PR` and high complexity to `READY FOR INDEPENDENT REVIEW` only from a positive structured and verifiable verdict
- [x] 4.6 Implement independent implementation code review for high complexity using a read-only reviewer prompt to a distinct agent, requiring a positive structured and verifiable verdict, returning actionable findings to Apply on rejection, and forbidding static `True` stubs or approval by absence of rejection
- [x] 4.7 Implement unit and integration tests in `tests/test_native_apply_and_verify.py` verifying dynamic workflow resolution, fail-closed handling for missing Verify and invocation errors, actual code modifications, exit-code-zero test execution with non-empty collection, Verify loops, and structured code review

## 5. Two-Phase Pull Requests, Documentation Closure, and Continuation Loop

- [x] 5.1 Implement `GitHubAdapter.merge_pull_request` method supporting merge commits, merge methods, candidate SHA verification, and typed success/failure results
- [x] 5.2 Deliver the minimal PR preparation skill (`minime-pr-preparer`) in F3 with structured input/output contract (generating title, description, test evidence, and informative issue reference strictly excluding auto-closing keywords for PR1 and PR2) and implement Phase 1 PR preparation invoking the skill without external F4 dependencies
- [x] 5.3 Implement differentiated merge policy for the first PR (auto-merge for low/moderate complexity; `HUMAN REQUIRED` for informational acknowledgement «Estoy enterado» in high complexity before merging), ensuring agent guardian directives do not impede coordinator-governed merges
- [x] 5.4 Implement fresh documentation branch (`doc-close-<numero>-<slug-kebab>`) and worktree creation rooted at the merged commit of `main` under the project's configured managed root
- [x] 5.5 Implement native OpenSpec Sync and OpenSpec Archive orchestration dynamically resolving native workflows (`opsx-sync`/`openspec-sync-specs` and `opsx-archive`/`openspec-archive-change`) executed by the thinking agent with lowest compatible effort in the documentation worktree, independently checking each workflow's exit, evidence, and resulting artifacts, and strictly forbidding Python `shutil.move` emulations
- [x] 5.6 Implement Phase 2 Documentation PR preparation invoking the minimal PR preparation skill and automatic merge regardless of initial complexity, confirming typed remote PR identity and head/base state
- [x] 5.7 Implement remote issue closure on GitHub with idempotent completion note and release of active project lock only after typed confirmation of PR1/PR2 remote merges, final Issue state, and closure result
- [ ] 5.8 Implement continuous FIFO transition automatically selecting and initiating the next eligible request upon confirmed completion, with idempotent continuation and safe Git error handling
- [x] 5.9 Implement tests in `tests/test_two_phase_pr_and_closure.py` covering minimal PR skill content generation and invocation for PR1/PR2 (verifying exclusion of auto-closing keywords and issue remaining open after PR1), typed merge policies, documentation worktree setup, independent native Sync/Archive results, PR2 auto-merge, typed issue closure, and Git failure recovery

## 6. End-to-End Proof and System Integration

- [x] 6.1 Implement CLI operator commands (`minime request run <project_id>`, `minime request list <project_id>`, `minime request ack <project_id>`) and REST API endpoints with verified F2 profiles/capabilities/budget bindings and the correct `operator_response` request boundary
- [x] 6.2 Implement PostgreSQL state persistence and continuity recovery tests in `tests/test_orchestration_continuity.py` verifying that technical errors and missing capabilities preserve worktree and run record, Git errors recover idempotently, and only confirmed closure or authorized cancellation releases lock
- [ ] 6.3 Execute authentic end-to-end integration test with low/moderate complexity in the existing `silverberdi/mini-me-r01-e2e-20261014` fixture proving dynamic OpenSpec workflow resolution, authentic agent invocation, exit-code-zero tests with non-empty collection, minimal PR skill execution, full cycle from remote issue to two merged PRs, and closure
- [ ] 6.4 Execute authentic end-to-end integration test with high complexity in the existing `silverberdi/mini-me-r01-e2e-20261014` fixture proving real workflow resolution for Explore, Propose, Verify, proposal review, automated test execution, structured positive code review, minimal PR skill invocation, «Estoy enterado», and closure
- [ ] 6.5 Verify strict non-deployment policy (no application deployment executed), scheduler disabled, worktree preservation during paused runs, no duplicate PRs/commits/comments under failure scenarios, and authentic FIFO selection of the next open Issue

## 7. Canonical Documentation and Configuration Reconciliation

- [x] 7.1 Reconcile `docs/CONTRATO_RECTOR.md` to incorporate the refined F3 rules (dynamic workflow resolution, Verify presence verification, minimal PR skill delivery, Explore prior to Propose, Verify by implementer, independent review only for high complexity, auto-merge for low/mod, informational ack for high, second PR auto-merge)
- [x] 7.2 Reconcile `docs/BACKLOG.md` and `AGENTS.md` aligning stage boundaries, roles, and verification criteria with F3 decisions
- [x] 7.3 Update `openspec/config.yaml` to reflect the refined F3 lifecycle transitions and prompt guidelines
- [x] 7.4 Audit and clean up dead code, retired functions, and obsolete imports within the F3 orchestration scope

