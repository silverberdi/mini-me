## Purpose

Enables mini me to coordinate an authorized real coding agent through its installed native OpenSpec workflow and deliver independently reviewed, checked software as a human-gated pull request. It defines the integrated first-delivery outcome without making mini me an OpenSpec or code author.

## ADDED Requirements

### Requirement: R01-S01 Secure admission of a READY change
Mini me SHALL admit execution only for one READY OpenSpec change bound by durable authority to the exact project, verified repository remote, GitHub Issue, change identity, and observed base SHA. It SHALL use the authorized owned worktree and SHALL NOT infer a repository from issue titles, labels, project fields, or agent output, create a second active execution for the same change, or authorize writes outside that worktree.

#### Scenario: Bound READY change admitted once
- **GIVEN** an isolated authorized fixture repository with a READY change, verified Issue, durable project/repository binding, observed base SHA, and no active execution for that change
- **WHEN** an authorized operator starts the real delivery flow
- **THEN** mini me creates or resumes exactly one durable Run/Job bound to those identities and prepares only its authorized worktree
- **AND** the persisted execution identity includes the repository remote, change, base SHA, generation, and stage.

#### Scenario: Missing or contradictory binding is denied
- **GIVEN** a missing, stale, ambiguous, or contradictory project/repository/Issue/change binding, or an unverified base identity
- **WHEN** admission is requested
- **THEN** mini me denies dispatch with a structured reason before provider inference or external mutation
- **AND** creates no duplicate Run, Job, branch, or worktree.

### Requirement: R01-S02 Preflight is authoritative and does not consume inference
Before any paid or subscription-provider inference, mini me SHALL verify the selected provider CLI and compatible installed native OpenSpec workflow, worktree ownership and Git identity, authentication/capacity evidence, execution policy, required skills/capabilities, and bounded authorization. A missing, stale, unknown, or contradictory prerequisite SHALL block dispatch without claiming provider failure or consuming an implementation attempt when the existing policy permits a preflight denial.

#### Scenario: Safe preflight passes
- **GIVEN** a bound READY fixture and current evidence for the installed provider CLI, native workflow, authentication, capacity, policy, and worktree
- **WHEN** preflight runs
- **THEN** it returns the exact authorized stage/provider/worktree identity and bounded dispatch permission without invoking inference.

#### Scenario: Adversarial preflight failure blocks inference
- **GIVEN** a missing native skill or CLI, invalid authentication, unavailable/insufficient capacity, stale health evidence, mismatched remote, symlink escape, or absent authorization
- **WHEN** preflight runs
- **THEN** it reports the specific blocking condition
- **AND** no provider inference, GitHub mutation, or unauthorized filesystem write occurs.

### Requirement: R01-S03 Apply uses the installed native agent-side OpenSpec workflow
The selected coding agent SHALL execute the installed, version-compatible agent-side OpenSpec `apply` workflow for the exact change. The workflow invocation SHALL use provider-supported syntax discovered from the installed capabilities; mini me SHALL NOT substitute a free-form programming prompt, invoke a guessed OpenSpec shell command, or treat `openspec validate` as agent workflow execution.

#### Scenario: Native workflow invocation is observed
- **GIVEN** an authorized APPLY dispatch with an installed compatible provider workflow
- **WHEN** the provider agent executes the change
- **THEN** evidence identifies the actual CLI/version, workflow or skill loaded, exact change and worktree, invocation result, and observed resulting artifacts/diff
- **AND** the evidence is corroborated by tool/process observation and repository state, not solely by agent-authored transcript text.

#### Scenario: Native workflow is unavailable or unproven
- **GIVEN** the requested workflow is absent, incompatible, or cannot be proven to have executed
- **WHEN** APPLY is requested or returns
- **THEN** mini me blocks or classifies the result as insufficient evidence
- **AND** does not claim successful OpenSpec application or create a successful candidate record.

### Requirement: R01-S04 Candidate and source changes remain bound to the owned worktree
The implementation SHALL remain within the exact authorized worktree and be bound to the original base SHA, current candidate SHA, generation, repository identity, and authoring attempt. Mini me SHALL observe real source changes and preserve uncommitted or committed candidate evidence across recoverable interruption; it SHALL NOT fabricate patches, commits, candidate files, task completion, or authorship.

#### Scenario: Real candidate is observed
- **GIVEN** a native APPLY run that changes fixture source files
- **WHEN** the stage returns
- **THEN** mini me records the actual diff/manifest and observed candidate SHA against the bound base
- **AND** verifies all changed paths are inside the assigned worktree and within the approved change scope.

#### Scenario: Interrupted apply preserves candidate evidence
- **GIVEN** an APPLY process is interrupted after a material diff but before stage acknowledgment
- **WHEN** the same durable Run/Job is recovered
- **THEN** mini me reconciles the existing worktree, diff, and checkpoint before any retry
- **AND** neither discards material work nor creates a duplicate execution identity.

### Requirement: R01-S05 Checks and independent review govern candidate progression
Mini me SHALL run the repository's configured deterministic checks and applicable installed OpenSpec verification workflow against the exact candidate. Authoritative review SHALL be read-only, bound to the frozen repository identity, candidate SHA, base SHA, generation, manifest, and surviving authorship, and performed by an identity distinct from every substantive author whose changes survive in that candidate. An eligible complementary primary is the normal reviewer. When no primary reviewer is eligible, DeepSeek Direct MAY satisfy the authoritative review gate only under an explicitly authorized, compatible, distinct read-only reviewer contract that receives sufficient candidate-bound input and returns a structured response accepted by deterministic validation. The existing DeepSeek audit runner or audit result SHALL NOT be converted into review evidence. If neither reviewer path is available and authorized, the candidate SHALL remain preserved in a truthful waiting state; no review result SHALL authorize human merge.

#### Scenario: Checks and distinct review authorize progression
- **GIVEN** a frozen candidate whose deterministic checks pass and whose required native verification evidence is valid
- **WHEN** a distinct eligible reviewer completes a read-only review of that exact candidate
- **THEN** mini me records the check and review evidence bound to that candidate identity
- **AND** advances only according to the existing policy and required authoritative evidence.

#### Scenario: Reviewer unavailable or candidate changes
- **GIVEN** no eligible independent reviewer is available, or the candidate SHA/base/generation changes after checks or review
- **WHEN** the pipeline attempts to advance
- **THEN** it waits or requires fresh checks/review for the new candidate
- **AND** does not reuse stale evidence, self-review, or mark the candidate PR-ready.

#### Scenario: DeepSeek review fallback is explicitly authorized and independently validated
- **GIVEN** no eligible primary reviewer can serve the frozen candidate and a compatible DeepSeek read-only review integration, sufficient review input, exact candidate binding, and explicit per-stage provider and budget authorization are verified
- **WHEN** DeepSeek Direct reviews the candidate under the distinct reviewer contract
- **THEN** the system validates a structured response deterministically, records review evidence bound to repository/base/head/generation/manifest and reviewer identity, and may satisfy the review gate only if the reviewer is distinct from all surviving substantive authors
- **AND** it does not derive approval from an audit record, omit required candidate context, or authorize human merge.

#### Scenario: DeepSeek review fallback is unavailable, incompatible, or unauthorized
- **GIVEN** no eligible primary reviewer can serve and DeepSeek compatibility, sufficient input, explicit provider authorization, or stage budget is absent or uncertain
- **WHEN** the pipeline evaluates review eligibility
- **THEN** it does not invoke DeepSeek, does not treat audit evidence as review, preserves the candidate, and remains in a truthful waiting or blocked state.

#### Scenario: Optional audit is not silently required or invoked
- **GIVEN** primary review and all required checks pass, with no explicit policy or human authorization requiring an independent fallback audit
- **WHEN** the candidate approaches the human PR gate
- **THEN** mini me does not require or silently invoke DeepSeek/OpenRouter audit
- **AND** any fallback audit is dispatched only after dual-primary unavailability, compatible tool capability, explicit authorization, and applicable budget approval.

### Requirement: R01-S06 PR delivery remains a human gate
After required checks and independent review pass, mini me SHALL publish or adopt a real Draft Pull Request whose remote head equals the exact candidate SHA and whose evidence links the bound Issue, OpenSpec change, base, checks, review, and execution lineage. It SHALL NOT merge, deploy, archive, close the change, or declare DONE without the corresponding human authority and later closure evidence.

#### Scenario: Candidate is published as an inspectable Draft PR
- **GIVEN** a verified candidate, successful required checks, authoritative independent review, and valid repository identity
- **WHEN** PR preparation executes
- **THEN** mini me creates or adopts one Draft PR with the exact candidate head and bound base/Issue/change references
- **AND** persists enough evidence for a human to inspect the candidate and stage outcomes.

#### Scenario: PR side effect is ambiguous or remote head conflicts
- **GIVEN** PR creation or branch publication has an unknown outcome or the remote head differs from the candidate SHA
- **WHEN** mini me reconciles the operation
- **THEN** it observes authoritative remote state before retry and fails closed on contradiction
- **AND** does not duplicate a PR, overwrite an unexpected branch, or expose an unverified candidate.

#### Scenario: Human merge is not automated
- **GIVEN** a Draft PR is ready for human review
- **WHEN** the workflow reaches its delivery gate
- **THEN** mini me stops with the exact PR/candidate evidence for human action
- **AND** performs no merge or production deployment.

### Requirement: R01-S07 Existing N01 evidence is preserved
The R01 fixture workflow SHALL preserve the original N01 Run, Job, attempts, OpenSpec modifications, worktree, ownership, snapshots, events, and external-action evidence. R01 SHALL NOT implement N01, replace its durable identities, consume provider capacity on N01, or fabricate recovery/continuation evidence to make the fixture pass.

#### Scenario: Fixture E2E leaves N01 unchanged
- **GIVEN** the durable N01 identities and an isolated fixture repository
- **WHEN** R01 tests and authorized fixture delivery execute
- **THEN** before/after evidence shows the same N01 Run/Job/history/worktree identities and unchanged protected state
- **AND** all fixture mutations are confined to the authorized disposable repository and its test authorities.

#### Scenario: N01 recovery cannot be proven safely
- **GIVEN** fixture delivery would require a production N01 mutation, missing recovery evidence, or unauthorized provider capacity
- **WHEN** the stage is evaluated
- **THEN** N01 remains untouched and the fixture may proceed only independently of N01
- **AND** the report states the N01 evidence gap without claiming recovery success.

### Requirement: R01-E01 Real end-to-end delivery in an authorized fixture
R01 acceptance SHALL include an externally observable, bounded end-to-end run using a small authorized disposable GitHub repository, a real READY OpenSpec change created through agent-side OpenSpec, a real compatible coding agent, real Git operations, deterministic checks, an independent reviewer, and a real Draft PR. Test doubles MAY cover isolated contracts only and SHALL NOT satisfy this product acceptance scenario.

#### Scenario: Real fixture change reaches a reviewable PR
- **GIVEN** an authorized disposable repository with a bound READY change covering success, rejection, and regression behavior, configured checks, explicit budget, and compatible distinct implementer/reviewer capacity
- **WHEN** the operator authorizes one bounded delivery run through the real API/CLI path
- **THEN** the real agent uses native OpenSpec apply and creates a functional source change in the owned worktree
- **AND** checks pass, the distinct reviewer evaluates the frozen candidate, and a real Draft PR is observable at the exact candidate SHA.

### Requirement: R01-E02 Provider workflow identity is proven
R01 SHALL demonstrate actual native workflow loading for the compatible Codex path used to implement the fixture; provider-specific workflow syntax and versions SHALL be observed, not assumed interchangeable. Antigravity execution is not a prerequisite for proving the Codex implementation path.

#### Scenario: Codex native workflow proof
- **GIVEN** the authorized R01 fixture and the installed supported Codex workflow
- **WHEN** Codex executes the APPLY stage
- **THEN** process/tool evidence proves Codex loaded the correct native OpenSpec workflow for the exact change
- **AND** generic text instructions, shell-only validation, or another provider's trace do not satisfy the proof.

#### Scenario: Antigravity is not a Codex acceptance prerequisite
- **GIVEN** the Codex native workflow and its evidence are compatible and verified
- **WHEN** R01 evaluates implementation-workflow acceptance
- **THEN** absence of Antigravity execution does not fail the Codex workflow proof or prevent that proof from passing.

### Requirement: R01-E03 Adversarial preflight is tested before paid inference
The integrated path SHALL have real or boundary-faithful tests for missing workflow/tool, invalid authentication, unavailable capacity, remote mismatch, path escape, and missing authorization, proving each applicable refusal occurs before inference or external mutation.

#### Scenario: Preflight denial has no side effects
- **GIVEN** one of the specified adversarial preflight conditions
- **WHEN** the actual admission/dispatch path evaluates it
- **THEN** the result identifies the exact failure and records no provider inference, unauthorized filesystem write, branch push, or PR mutation.

### Requirement: R01-E04 Interrupted delivery resumes durably
The integrated workflow SHALL prove that a process/daemon interruption after material candidate progress preserves the same Run, Job, branch, worktree, and evidence, and that replay reconciles prior external side effects before retrying.

#### Scenario: Interruption between candidate and PR checkpoint
- **GIVEN** a real fixture run interrupted after candidate changes exist but before PR completion
- **WHEN** the service restarts and the same authorized run is resumed
- **THEN** it adopts the original candidate evidence and produces at most one matching PR
- **AND** creates no duplicate Run, Job, branch, or unobserved repeated external action.

### Requirement: R01-E05 Reviewer independence is adversarially enforced
The integrated path SHALL prove that same-author review and stale-candidate review cannot authorize PR readiness.

#### Scenario: Same implementer attempts authoritative review
- **GIVEN** a candidate substantively authored by one provider/model identity
- **WHEN** that same identity attempts to provide its authoritative review
- **THEN** the review is rejected and the candidate remains blocked from PR-ready state.

#### Scenario: Reviewer evidence is stale
- **GIVEN** review evidence for a candidate SHA that no longer matches the current frozen candidate
- **WHEN** advancement is attempted
- **THEN** the review is historical only and fresh independent review is required.

### Requirement: R01-E06 N01 preservation is checked independently
The R01 acceptance evidence SHALL compare protected N01 durable and filesystem state before and after fixture execution without using N01 as the execution fixture.

#### Scenario: N01 identities and evidence remain unchanged
- **GIVEN** read-only before-state evidence for N01 and a separate disposable fixture
- **WHEN** the complete fixture scenario runs
- **THEN** the after-state comparison confirms no N01 Run/Job/attempt/worktree/OpenSpec/external-action mutation or new N01 inference occurred.

### Requirement: R01-E07 Functional post-deployment behavior is proven
R01 SHALL be verified after authorized deployment by repeating a low-cost fixture operation through the actual API/CLI and observing the functional delivery result, not merely service health.

#### Scenario: Deployed fixture path produces its promised outcome
- **GIVEN** the authorized target deployment and a disposable bound fixture with a bounded approval
- **WHEN** the deployed API/CLI path executes the agreed functional acceptance scenario
- **THEN** a real candidate and inspectable PR at the expected SHA are observed
- **AND** health-only checks or mocked provider/process responses are not reported as deployed functional success.
