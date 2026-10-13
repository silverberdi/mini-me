## 1. Baseline, scope, and authorities

- [ ] 1.1 Revalidate the authorized base, repository identity, active OpenSpec changes, PR #140/#152 status, current N01 evidence, installed OpenSpec/provider workflow versions, and relevant caller/configuration graph; record facts and unresolved execution blockers without changing protected state.
- [ ] 1.2 Map R01-S01–S07 and R01-E01–E07 to this change's scenarios, responsible existing authorities, deterministic tests, real E2E evidence, and post-deployment evidence; confirm no R02/R04/future-stage scope was introduced.
- [ ] 1.3 Complete the verified code/consumer census and Removal Ledger for prompt-emulation and workflow-dispatch paths, callers, configuration, tests, and docs; record exact symbols/call sites and classify each REUSE/MODIFY/REPLACE/REMOVE/RETAIN-WITH-REASON, with parity evidence required before removal and human approval for RETAIN-WITH-REASON where required by engineering policy.
- [ ] 1.4 Reconcile the affected OpenSpec and canonical DeepSeek role statements, including `docs/AGENT_CONTRACTS.md` and `docs/CANONICAL_DECISIONS.md`, so the approved conditional read-only reviewer role is explicit before enablement; preserve fallback-after-primary-unavailability, per-stage authorization/budget, auditor/reviewer separation, and human-only merge/closure. Keep audits conditional on applicable policy or explicit human authorization.

## 2. Secure admission and preflight — R01-S01/S02, R01-E03

- [ ] 2.1 Implement or connect preflight to the existing durable project/repository/Issue/change/base binding and owned-worktree authorities; test missing, stale, contradictory, duplicate-run, wrong-remote, and path/symlink escape denials.
- [ ] 2.2 Resolve installed Codex CLI version and native OpenSpec apply workflow name/options; test that absent, incompatible, or unobservable workflow evidence blocks before inference and creates no unauthorized external effects. Antigravity is not required for Codex execution acceptance.
- [ ] 2.3 Integrate current authentication/capacity/policy/budget evidence with a bounded authorized dispatch; verify unknown or unavailable prerequisites preserve work and wait/block truthfully without inference.

## 3. Native OpenSpec agent execution and candidate evidence — R01-S03/S04, R01-E02/E04

- [ ] 3.1 Route APPLY through the existing runner/orchestration authority with the exact change, stage, Codex native workflow, generation, scope, owned worktree, timeout, and idempotency context; prove the actually installed Codex workflow is invoked. Do not require Antigravity for this proof.
- [ ] 3.2 Capture and redact process/tool/version/workflow evidence, then corroborate it with observed OpenSpec artifacts, allowed file manifest, diff, and exact candidate/base SHA; reject transcript-only claims and out-of-scope mutations.
- [ ] 3.3 Exercise interruption after material candidate progress and before acknowledgment; prove same Run/Job/worktree and side-effect reconciliation on resume without duplicate execution, lost candidate work, or blind replay.

## 4. Checks, independent review, and policy alignment — R01-S05/E05

- [ ] 4.1 Run configured deterministic checks and supported native OpenSpec verification against the exact frozen candidate; bind results to repository, base/head SHA, generation, and manifest, and test stale or failed evidence denial. Verify pre-apply validation cannot by itself authorize scheduler admission.
- [ ] 4.2 Enforce candidate-author/reviewer identity separation and mixed-authorship rules; adversarially verify same-identity review and stale-candidate review cannot authorize progression.
- [ ] 4.3 Reconcile orchestration/reviewer requirements and dispatch gates so an eligible independent primary is the normal reviewer and DeepSeek Direct can act as authoritative read-only reviewer only when no eligible primary exists, capability and complete review input are verified, the distinct review response is structured and deterministically validated, and explicit per-stage provider/budget authorization exists; prove audit records/results cannot be converted into review evidence.
- [ ] 4.4 When neither an eligible primary reviewer nor a compatible, explicitly authorized DeepSeek reviewer is available, verify candidate/worktree preservation and a truthful waiting/blocked state with no self-review or false PR-ready result; prove successful review never bypasses human merge.

## 5. Real fixture delivery and human gate — R01-S06, R01-E01

- [ ] 5.1 Provision or identify one explicitly authorized disposable GitHub fixture with real remote, repository instructions, OpenSpec configuration, a READY change authored through native agent-side propose, a failing behavior test, bound Issue, deterministic checks, and a branch/PR path.
- [ ] 5.2 Execute one budgeted real-agent fixture APPLY through the actual API/CLI admission path; verify functional source behavior, native workflow/tool evidence, candidate lineage, and passing deterministic checks in the owned worktree.
- [ ] 5.3 Obtain distinct authoritative review of the frozen candidate from an eligible complementary primary, or from DeepSeek Direct only under the separately verified and explicitly authorized read-only reviewer contract; reconcile/publish one real Draft PR whose remote head equals the candidate and whose evidence links Issue/change/base/check/review/run; test ambiguous side effects and remote-head mismatch fail closed. If no qualifying reviewer or provider/budget authorization exists, preserve the candidate and leave delivery waiting rather than claiming completion.
- [ ] 5.4 Verify human merge remains mandatory and no automatic merge, archive, closure, scheduler activation, or unapproved deployment occurs.

## 6. N01 preservation and retirement regression — R01-S07, R01-E06

- [ ] 6.1 Capture redacted, read-only before-state evidence for N01 Run/Job/attempts/events, OpenSpec changes, ownership/worktree/snapshot, candidate absence, and external actions without invoking N01.
- [ ] 6.2 Run the isolated fixture while proving N01 records, files, worktree, ownership, and actions remain unchanged; investigate any discrepancy without repairing N01.
- [ ] 6.3 After real-path parity, migrate callers and remove only prompt-emulation routes proven replaced in the Removal Ledger; preserve orchestration, task tracking, validators, intake generation (R02), closure/sync (R04), histories, and safety guards with justified consumers.
- [ ] 6.4 Repeat affected unit/integration, security-denial, interruption/recovery, stage E2E, full fixture delivery E2E, and no-duplicate-path checks after retirement; retain evidence bound to the final candidate.

## 7. Functional post-deployment acceptance and closure evidence — R01-E07

- [ ] 7.1 Deploy only after human merge and authorized release; record exact source SHA and immutable deployment identity, rollback point, migration status, and scheduler state.
- [ ] 7.2 Execute the bounded fixture acceptance through the actual deployed API/CLI and observe functional implementation, checks, independent review, and exact Draft PR; distinguish TECHNICAL_PASS, E2E_PASS, and DEPLOYED_VERIFIED.
- [ ] 7.3 Assemble the requirement→scenario→test→evidence matrix, review/retirement ledger, cost/provider authorization, PR/merge/deployment identities, N01 preservation comparison, and any WAITING/NOT_VERIFIED limitations; do not mark DONE while applicable DoD evidence is missing.
