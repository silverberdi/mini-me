## 1. Remote Request Intake and Selection

- [ ] 1.1 Extend `GitHubAdapter.list_issues` to support exhaustive multi-page pagination across all open issues without silent omission of older tickets
- [ ] 1.2 Implement `RemoteRequestIntakeService` to query remote repository issues, order them ascending by `created_at` (FIFO), and apply deterministic tie-breaking on issue number
- [ ] 1.3 Add filtering in `RemoteRequestIntakeService` to exclude issues tagged `disabled` or having open dependency issues, preserving their original FIFO priority when unblocked
- [ ] 1.4 Enforce the single active Request constraint per project in `RemoteRequestIntakeService` and recognize re-entrant executions without creating duplicate runs
- [ ] 1.5 Implement comprehensive unit tests in `tests/test_remote_request_intake.py` verifying FIFO ordering, pagination, exclusion rules, and single-active-request enforcement

## 2. Git Workspace Isolation and Agent Process Confinement

- [ ] 2.1 Enhance `WorktreeManager` to create and track candidate branches named `request-<numero>-<slug-kebab>` from the latest remote reference of the configured base branch
- [ ] 2.2 Consolidate agent execution mechanics into `CliAgentRunner` supporting `thinker`, `implementer`, and `reviewer` roles under `AgentProcessConfinement`
- [ ] 2.3 Integrate preflight verification of provider health, quota availability, and budget limits via `CapacityLifecycleService` and `BudgetService` before each agent invocation
- [ ] 2.4 Implement tests in `tests/test_workspace_isolation_and_agent_confinement.py` verifying branch creation, worktree sandboxing, and capacity preflight gating

## 3. Native OpenSpec Propose and Validation Loop

- [ ] 3.1 Implement OpenSpec Explore orchestration dispatching the official Explore workflow to the thinking agent in the confined worktree
- [ ] 3.2 Implement autonomous ambiguity clarification in Explore and the `HUMAN REQUIRED` protocol for true material ambiguities, preserving verbatim OpenSpec text and Spanish options
- [ ] 3.3 Implement OpenSpec Propose orchestration dispatching the official Propose workflow to generate canonical change artifacts (`proposal.md`, `specs/`, `design.md`, `tasks.md`)
- [ ] 3.4 Implement strict CLI validation executing `openspec validate <change> --strict --no-interactive` with an automatic correction pass by the thinking agent upon validation failure
- [ ] 3.5 Implement LLM-grounded complexity evaluation (`low`, `moderate`, `high`) recorded by the thinking agent upon successful validation
- [ ] 3.6 Implement independent proposal review for high-complexity changes using a read-only reviewer prompt and routing defects back to the thinking agent
- [ ] 3.7 Implement unit and integration tests in `tests/test_native_propose_lifecycle.py` covering Explore, Propose, CLI Validate loops, complexity assessment, and proposal review

## 4. Native OpenSpec Apply, Test Execution, and Verify

- [ ] 4.1 Implement OpenSpec Apply orchestration dispatching the official Apply workflow to the implementer agent in the candidate worktree
- [ ] 4.2 Enforce mandatory unit and E2E test execution during Apply, verifying that tests pass with exit code 0 and test evidence is recorded before completing Apply
- [ ] 4.3 Implement OpenSpec Verify orchestration executed by the same implementer agent (not the thinking agent) using verified project context
- [ ] 4.4 Implement Verify failure feedback loop delivering the authentic findings report to the implementer in an Apply correction prompt
- [ ] 4.5 Implement post-Verify complexity routing: transition low/moderate complexity to `READY FOR PR` and high complexity to `READY FOR INDEPENDENT REVIEW`
- [ ] 4.6 Implement independent implementation code review for high complexity using a read-only reviewer prompt, returning actionable findings to Apply on rejection
- [ ] 4.7 Implement unit and integration tests in `tests/test_native_apply_and_verify.py` verifying task completion, automated test execution, Verify loops, and code review

## 5. Two-Phase Pull Requests, Documentation Closure, and Continuation Loop

- [ ] 5.1 Implement `GitHubAdapter.merge_pull_request` method supporting merge commits, merge methods, and candidate SHA verification
- [ ] 5.2 Implement Phase 1 Implementation PR creation from the request branch to base branch, verifying branch protections and permissions
- [ ] 5.3 Implement differentiated merge policy for the first PR: auto-merge for low/moderate complexity; `HUMAN REQUIRED` for informational acknowledgement («Estoy enterado») in high complexity before merging
- [ ] 5.4 Implement fresh documentation branch (`doc-close-<numero>-<slug-kebab>`) and worktree creation rooted at the merged commit of `main`
- [ ] 5.5 Implement native OpenSpec Sync and OpenSpec Archive orchestration executed by the thinking agent with lowest compatible effort in the documentation worktree
- [ ] 5.6 Implement Phase 2 Documentation PR creation and automatic merge regardless of initial complexity
- [ ] 5.7 Implement remote issue closure on GitHub with idempotent completion note and release of active project lock
- [ ] 5.8 Implement continuous FIFO transition automatically selecting and initiating the next eligible request upon completion
- [ ] 5.9 Implement tests in `tests/test_two_phase_pr_and_closure.py` covering PR1 merge policies, documentation worktree setup, Sync/Archive, PR2 auto-merge, and issue closure

## 6. End-to-End Proof and System Integration

- [ ] 6.1 Implement CLI operator commands (`minime request run <project_id>`, `minime request list <project_id>`, `minime request ack <project_id>`) and REST API endpoints
- [ ] 6.2 Implement PostgreSQL state persistence and crash recovery tests in `tests/test_orchestration_continuity.py` verifying idempotent resume across daemon restarts
- [ ] 6.3 Execute authentic end-to-end integration test with low/moderate complexity proving the full cycle from remote issue to two merged PRs and closure
- [ ] 6.4 Execute authentic end-to-end integration test with high complexity proving Explore, proposal review, automated test execution, code review, human acknowledgement, and closure
- [ ] 6.5 Verify that worktrees are cleaned up, git protections are respected, and no duplicate PRs, commits, or comments are created under failure scenarios

## 7. Canonical Documentation and Configuration Reconciliation

- [ ] 7.1 Reconcile `docs/CONTRATO_RECTOR.md` to incorporate the refined F3 rules (Explore prior to Propose, Verify by implementer, independent review only for high complexity, auto-merge for low/mod, informational ack for high, second PR auto-merge)
- [ ] 7.2 Reconcile `docs/BACKLOG.md` and `AGENTS.md` aligning stage boundaries, roles, and verification criteria with F3 decisions
- [ ] 7.3 Update `openspec/config.yaml` to reflect the refined F3 lifecycle transitions and prompt guidelines
- [ ] 7.4 Audit and clean up dead code, retired functions, and obsolete imports within the F3 orchestration scope
