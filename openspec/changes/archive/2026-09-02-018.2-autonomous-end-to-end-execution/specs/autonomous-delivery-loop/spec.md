# Spec: Autonomous Delivery Loop

## Requirement: 15-Phase Autonomous Pipeline Execution
The orchestrator SHALL natively progress an admitted READY work item through all 15 canonical SDLC stages without requiring manual supervisor intervention between stages.

### Scenarios

#### Scenario: Autonomous End-to-End Progression to READY_FOR_HUMAN_MERGE
- GIVEN a registered project with a bound GitHub Issue and an OpenSpec change satisfying Definition of Ready (DoR),
- WHEN the autonomous scheduler tick executes with `drive_admitted=True`,
- THEN `mini me` SHALL:
  1. Discover the work item via `WorkDiscoveryService`,
  2. Verify readiness via `ReadinessService`,
  3. Admit the candidate via `SchedulerService.admit_work_item()`,
  4. Create an `OrchestrationRun` in `ADMITTED` and queue a `Job` in `PREPARING_EXECUTION`,
  5. Select Codex as default implementer under `ProviderPolicyService`,
  6. Provision an isolated worktree under `.minime/worktrees/`,
  7. Execute the implementer in the worktree,
  8. Freeze the candidate SHA and persist a non-empty `CandidateManifest`,
  9. Execute all configured project checks and verify exit code 0,
  10. Execute independent complementary review on a read-only snapshot,
  11. Validate reviewer independence (disqualifying any material candidate author),
  12. Execute DeepSeek Direct read-only audit and verify 0 blocking findings,
  13. Validate preview authority if UI-affecting, or bypass cleanly if non-UI,
  14. Push the candidate branch to remote `origin` and create/adopt the GitHub PR,
  15. Transition the run to `stop_outcome=READY_FOR_HUMAN_MERGE` with `human_gate=READY_FOR_HUMAN_MERGE`.

#### Scenario: Provider Policy Compliance
- GIVEN an admitted work item executing under normal conditions,
- WHEN the implementer is selected,
- THEN Codex SHALL be chosen as the default implementer, and Antigravity SHALL NOT be assigned for routine implementation without a persisted `PremiumProviderReasonCode`.
