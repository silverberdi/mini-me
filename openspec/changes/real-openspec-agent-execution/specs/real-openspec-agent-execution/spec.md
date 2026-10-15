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

#### Scenario: Adversarial admission: mismatched remote identity or forged issue binding
- **GIVEN** an admission request with an issue title, label, or external body referencing a repository different from the durable project binding
- **WHEN** scheduler admission evaluates the request
- **THEN** mini me rejects the request immediately with an explicit binding violation
- **AND** refuses to clone, fetch, or mutate any remote repository or create an execution record.

#### Scenario: Adversarial admission: concurrency race attempting duplicate active run
- **GIVEN** an active Run/Job already exists in state IMPLEMENTING or WAITING_CAPACITY for a change
- **WHEN** a concurrent or replay admission request arrives for the same change
- **THEN** mini me locks the change row, detects the existing active execution, and rejects duplicate admission without spawning parallel workers or creating a second Job.

#### Scenario: Adversarial admission: stale base SHA mismatch against canonical repository ref
- **GIVEN** the repository base commit observed by mini me has advanced beyond the base SHA recorded in the READY change binding
- **WHEN** admission validates the base ref
- **THEN** mini me rejects the stale candidate dispatch, marks the change NOT_READY for base divergence, and requires an explicit OpenSpec rebase or update.

### Requirement: R01-S02 Preflight is authoritative and does not consume inference
Before any paid or subscription-provider inference, mini me SHALL verify the selected provider CLI and compatible installed native OpenSpec workflow, worktree ownership and Git identity, authentication/capacity evidence, execution policy, required skills/capabilities, and bounded authorization. Each project SHALL configure provider, model, and effort independently for PLAN, CONTRACT REVIEW, APPLY, TEST, VERIFY/E2E, and final REVIEW. Before dispatch, mini me SHALL verify that the exact installed CLI/version supports the configured provider/model/effort tuple, role, and native workflow; missing or ambiguous compatibility SHALL fail closed. It SHALL choose the least-cost configured profile meeting the stage's documented complexity/risk floor and workflow/tool needs using an explicit verified cost basis; unknown cost SHALL NOT be treated as zero or proof of least cost. Complexity/risk floors SHALL come from existing project policy, durable change requirements, or deterministic criteria; local-AI classifications MAY inform preparation but SHALL NOT bind or raise the required tier. Premium models and maximum effort SHALL NOT be defaults. Any escalation SHALL require objective evidence, recorded justification, finite stage/failure bounds, and explicit budget authorization. R01 SHALL reuse existing configuration, provider adapters/capabilities, capacity and budget authorities; it SHALL NOT add a second selector/scheduler or dynamic optimizer. A missing, stale, unknown, or contradictory prerequisite SHALL block dispatch without claiming provider failure or consuming an implementation attempt when the existing policy permits a preflight denial. Authentication, CLI presence, model catalogs, human authorization, and a correctly shaped JSON object are not capacity evidence. Optional local AI MAY assist with preliminary complexity classification, context preparation/reduction, extraction, labeling, and auxiliary tasks, but SHALL NOT diagnose failures, implement authoritatively, review security, or make binding decisions; its absence or failure SHALL NOT block the pipeline.

For Antigravity, authoritative `/usage` capacity SHALL be derived only from the registered adapter's bounded invocation of the configured, resolved AGY executable whose path/version passed provider capability preflight, using the supported read-only headless command. The adapter SHALL bind the exact child process identity, exit status, stdout payload, start/completion timestamps, and fresh private per-invocation auth log to one observation. Parser-only JSON, caller/agent-supplied observations, stale logs, or `statusLine` callbacks SHALL NOT authorize persistence or dispatch. The auth log SHALL contain an unambiguous successful account identity for the supported authentication method; missing, unsupported, malformed, or conflicting identities fail closed. Account identity SHALL be redacted before durable storage. This is controlled local CLI provenance, not cryptographic or provider-server attestation.

The payload SHALL explicitly include `status: SUCCESS`, `num_turns: 0`, a `usage` object with non-boolean integer `total_tokens`, `input_tokens`, and `output_tokens` all explicitly present and equal to zero, `command.name: usage`, and the complete supported quota group/buckets. Optional token counters, when present, SHALL be valid non-boolean integers equal to zero. Missing values SHALL NEVER be defaulted to zero. Duplicate conflicting group/bucket records, malformed values, nonzero usage, or nonzero process exit fail closed.

The observed account SHALL match the account selected for the stage. The selected configured model SHALL be bound to a supported quota-group/bucket mapping; a generic group label or human-readable description SHALL NOT establish model membership by itself. Every required bucket SHALL have a unique supported ID, a finite numeric fraction in `[0, 1]`, and an unambiguous timezone-aware reset time strictly later than invocation completion. Reset-at-or-before-completion, malformed reset, or a model/quota-scope mismatch yields UNKNOWN. A valid zero fraction is EXHAUSTED, not AVAILABLE. Observation time SHALL be the controlled invocation completion time and expiry SHALL be no later than 60 seconds after it.

Antigravity `statusLine` telemetry SHALL NOT authorize dispatch under this contract; it MAY be retained only as non-authoritative informative telemetry. An otherwise plausible payload without acquisition, identity, freshness, and model-scope proof remains UNKNOWN.

#### Scenario: Safe preflight passes
- **GIVEN** a bound READY fixture and current evidence for the configured stage provider/model/effort, installed CLI/version and native workflow, authentication, capacity, policy, budget, and worktree
- **WHEN** preflight runs
- **THEN** it returns the exact authorized stage/provider/model/effort/worktree identity and bounded dispatch permission without invoking inference.

#### Scenario: Unsupported or unknown model/effort is refused
- **GIVEN** a stage profile names a model, effort, role, or workflow that the exact installed CLI/version does not advertise or whose compatibility cannot be verified
- **WHEN** preflight resolves the stage profile
- **THEN** mini me refuses dispatch without guessing a provider default, invoking inference, or changing the configured profile.

#### Scenario: Cheapest competent configured profile is selected
- **GIVEN** multiple authorized profiles for a stage pass actual CLI/workflow, capacity, and budget checks and meet the documented complexity/risk floor
- **WHEN** mini me resolves the initial stage profile
- **THEN** it selects the lowest-cost eligible configured profile and records the capability, model, effort, cost basis, and policy decision
- **AND** it does not select a premium model or maximum effort merely as a default.

#### Scenario: Unknown cost cannot be called least-cost
- **GIVEN** multiple otherwise eligible stage profiles lack a verified comparable cost basis
- **WHEN** mini me resolves the initial profile
- **THEN** it does not claim a cost-optimal selection or silently treat unknown cost as zero
- **AND** it uses only an explicitly approved bounded profile if existing policy authorizes that selection, otherwise preserves the work and waits.

#### Scenario: Escalation needs evidence and budget authority
- **GIVEN** an initial stage profile fails an objective documented criterion and a higher-cost profile is proposed
- **WHEN** mini me evaluates escalation
- **THEN** escalation proceeds only with a recorded objective reason, bounded limit, and explicit budget authorization
- **AND** otherwise the work remains preserved in a waiting/blocked state.

#### Scenario: Local AI assistance is non-authoritative and optional
- **GIVEN** a local helper is unavailable, fails, or returns a complexity/context suggestion
- **WHEN** the pipeline prepares or evaluates a stage
- **THEN** helper absence/failure does not block the stage and its output cannot diagnose a failure, authorize a model/effort escalation, implement, review security, or make a binding decision.

#### Scenario: Adversarial preflight failure blocks inference
- **GIVEN** a missing native skill or CLI, invalid authentication, unavailable/insufficient capacity, stale health evidence, mismatched remote, symlink escape, or absent authorization
- **WHEN** preflight runs
- **THEN** it reports the specific blocking condition
- **AND** no provider inference, GitHub mutation, or unauthorized filesystem write occurs.

#### Scenario: Unknown or stale capacity is not execution permission
- **GIVEN** provider capacity is absent, unknown, contradictory, or older than its bounded freshness lifetime
- **WHEN** scheduler admission evaluates the required implementer/reviewer pair
- **THEN** the affected provider remains unavailable for dispatch and the work is preserved in a truthful wait state
- **AND** authentication status, model catalogs, reset estimates, or human execution authorization do not substitute for current capacity evidence.

#### Scenario: Physical schema readiness follows the canonical Alembic graph
- **GIVEN** the repository has one canonical Alembic head and the isolated PostgreSQL schema is at that head
- **WHEN** readiness performs its physical schema preflight
- **THEN** it accepts only that migration head and verifies all required model tables and columns
- **AND** a database at an ancestor revision remains NOT_READY without stamping, downgrading, or repairing schema state.

#### Scenario: Codex capacity is read without inference
- **GIVEN** the installed Codex App Server exposes `account/rateLimits/read`
- **WHEN** mini me reads provider capacity
- **THEN** it accepts only an explicit boolean `ordinaryUsageAllowed` for the Codex limit bucket and a returned active account identity
- **AND** null, missing, failed, or expired observations remain UNKNOWN without invoking a Codex turn.

#### Scenario: Antigravity capacity is read via headless print-mode /usage without inference
- **GIVEN** the installed Antigravity CLI exposes the read-only `/usage` command in headless print mode (`-p`)
- **WHEN** mini me obtains a read-only capacity observation
- **THEN** it accepts only an explicit non-inference response (`num_turns: 0` and verified zero token consumption), bound to the authenticated account fingerprint (derived from private silent auth logs), the active Gemini model group, and all required Gemini quota buckets whose remaining fractions and reset fields are valid and consistent
- **AND** it stores only the account fingerprint and normalized evidence, never the account email or credentials
- **AND** it operates without mutating `settings.json`, without launching an interactive TUI, and without interfering with any concurrent or pre-existing AGY CLI sessions.

#### Scenario: Antigravity /usage evidence with missing or incomplete fields fails closed as UNKNOWN
- **GIVEN** `/usage` output lacks `num_turns`, `usage`, any required token counter (`total_tokens`, `input_tokens`, or `output_tokens`), required quota buckets, fractions, or reset fields, or contains incomplete or unparseable fields
- **WHEN** mini me evaluates the observation
- **THEN** missing or incomplete fields SHALL NEVER be defaulted to zero consumption or assumed available
- **AND** without positive proof of non-inferential execution and active quota, capacity remains UNKNOWN and the provider is not dispatched.

#### Scenario: AGY capacity provenance is bound to one controlled CLI invocation
- **GIVEN** a candidate `/usage` JSON payload is structurally valid
- **WHEN** it was not emitted as stdout by the configured resolved AGY child process with successful exit and its own fresh private invocation log
- **THEN** it cannot be persisted as authoritative capacity, regardless of its `source_signal` field or plausible contents
- **AND** parser-only JSON, caller-created observations, agent transcript, statusLine callback, and pre-existing log files yield UNKNOWN.

#### Scenario: AGY account identity evidence is missing or ambiguous
- **GIVEN** the per-invocation authentication log has no successful supported auth event, uses an unsupported auth method, has malformed identity, or contains conflicting successful account identities
- **WHEN** the adapter normalizes the `/usage` response
- **THEN** the account is not inferred from stdout, environment, another AGY session, or prior observations
- **AND** capacity remains UNKNOWN and no provider stage is dispatched.

#### Scenario: AGY selected model matches the observed quota scope
- **GIVEN** `/usage` reports a provider quota group and the execution policy selects a concrete AGY model
- **WHEN** mini me checks model capacity
- **THEN** the selected model must match an explicit supported model-to-quota-scope mapping for every required bucket
- **AND** generic group names, descriptive prose, unsupported models, or ambiguous/duplicate bucket IDs cannot authorize dispatch.

#### Scenario: AGY quota reset and observation freshness are current
- **GIVEN** `/usage` contains otherwise valid quota buckets
- **WHEN** the observation is future-dated, older than the TTL, expires after more than 60 seconds, has a malformed reset, or any required reset is at/before observation time
- **THEN** the observation is UNKNOWN/stale and cannot authorize admission or stage dispatch.

#### Scenario: AGY acquisition, persistence, and dispatch gates reject forged evidence
- **GIVEN** a test or internal caller constructs a positive `CapacityObservation` or supplies parser JSON without invoking the registered adapter's controlled read
- **WHEN** capacity persistence or the final JIT dispatch gate evaluates it
- **THEN** it is rejected as non-authoritative and the normalized state remains UNKNOWN
- **AND** no Run/Job, provider attempt, or provider inference is created by that rejected evidence.

#### Scenario: Antigravity statusLine is non-authoritative telemetry and cannot authorize dispatch
- **GIVEN** Antigravity produces `statusLine` telemetry (from terminal hooks, environment variables, or background processes)
- **WHEN** scheduler admission or stage dispatch evaluates capacity
- **THEN** `statusLine` SHALL NOT be accepted as authoritative capacity evidence under this R01 contract
- **AND** it MAY be retained as secondary or informative telemetry, but dispatch authorization strictly requires a controlled `/usage` acquisition with corroborated local process, account, freshness, and model/quota-scope evidence.

#### Scenario: Mandatory provider capacity regressions for Antigravity
- **GIVEN** the Antigravity provider capacity validation suite
- **WHEN** regression checks execute
- **THEN** deterministic tests MUST cover, at minimum:
  1. `incomplete_schema`: independently missing `num_turns`, `usage`, each required token counter including `output_tokens`, group/bucket, fraction, or reset never defaults to zero and yields UNKNOWN
  2. `forged_or_contradictory_payload`: nonzero/boolean/malformed counters, duplicate conflicting groups/buckets, or inconsistent fractions/resets fail closed
  3. `stale_payload`: expired TTL, future observation, or reset-at/before observation blocks dispatch
  4. `acquisition_provenance`: parser-only or caller-created JSON/observation, stale/missing log, wrong executable, failed exit, timeout, or conflicting auth events cannot authorize persistence
  5. `identity_and_model_scope`: wrong account/auth method, unsupported selected model, or unmapped/ambiguous quota scope yields UNKNOWN
  6. `persistence_and_dispatch`: positive-looking evidence not produced by a successful registered-adapter acquisition is rejected by persistence and JIT dispatch without Run/Job/attempt/inference side effects
  7. `valid_signal`: successful controlled non-inferential `/usage`, unambiguous account identity, explicit zero required counters, supported selected-model/quota mapping, current unique buckets and positive fractions produces AVAILABLE.

#### Scenario: Antigravity /usage evidence is unavailable or ambiguous
- **GIVEN** `/usage` data is absent, stale, malformed, indicates turn or token execution, is for another account/model group, has missing or inconsistent quota buckets, has non-zero exit code, or times out
- **WHEN** mini me evaluates Antigravity capacity
- **THEN** capacity remains UNKNOWN and the provider is not dispatched
- **AND** the adapter does not infer capacity from authentication or model listing alone, or claim the quota is exhausted.

#### Scenario: Unrelated AGY session does not prevent controlled observation
- **GIVEN** one or more AGY CLI processes already exist (such as long-lived interactive sessions), and mini me executes its bounded headless `/usage` observer in a private isolated temporary directory
- **WHEN** mini me evaluates the observation
- **THEN** it accepts the fresh structured quota observation without signaling, terminating, or modifying existing processes, their terminals, or shared settings.

#### Scenario: Admission refreshes both primary capacity strategies just in time
- **GIVEN** a READY change requires an implementer/reviewer pair and either persisted capacity observation is stale or near expiry
- **WHEN** the canonical admission command prepares its decision
- **THEN** the registered provider strategies are queried for both required primary roles before admission locks are acquired
- **AND** only normalized, unexpired observations are re-read under the admission locks
- **AND** unknown, exhausted, failed, or expired observations produce WAIT without creating a Run or Job.

#### Scenario: Dispatch and review require stage-local fresh capacity
- **GIVEN** an APPLY or REVIEW stage is about to invoke its selected provider
- **WHEN** the pipeline performs its final pre-dispatch check
- **THEN** it obtains a fresh read-only observation for that stage's provider before creating an implementation attempt or transitioning to REVIEW_RUNNING
- **AND** unavailable evidence preserves the same candidate/worktree and waits without invoking the provider
- **AND** expiration after a stage has already passed this gate does not retroactively revoke that stage; the next provider stage obtains its own fresh observation.

#### Scenario: Adversarial preflight: path escape or symlink traversal attempt
- **GIVEN** a preflight request or environment containing relative path traversal (`../`), symlinked worktree paths outside the authorized root, or unverified external directory mounts
- **WHEN** ManagedWorkspaceGuard and preflight confinement execute
- **THEN** mini me immediately denies execution with a structured security violation before invoking any provider CLI
- **AND** refuses to read, write, or execute commands in the target path.

#### Scenario: Capacity failure propagates strictly to WAITING_CAPACITY dispatch block
- **GIVEN** an authoritative capacity read returns UNKNOWN (due to missing fields, incomplete counters, uncorroborated statusLine, or expired TTL) or EXHAUSTED (zero remaining fraction)
- **WHEN** scheduler admission or stage dispatch evaluates execution eligibility
- **THEN** mini me sets the job state to WAITING_CAPACITY without invoking provider inference
- **AND** records an explicit capacity wait event without creating a failed attempt or escalating to NEEDS_HUMAN.

### Requirement: R01-S03 Apply uses the installed native agent-side OpenSpec workflow
The R01 stage assignment SHALL be Codex for PLAN and read-only VERIFY/E2E; DeepSeek Direct preferred for read-only CONTRACT REVIEW only with compatible capability, fresh capacity, and explicit stage/provider/budget authorization (AGY is the alternative); and AGY for APPLY and implementation TEST. Final REVIEW SHALL follow the separate existing candidate-independence policy. Each selected agent SHALL execute only the installed, version-compatible native workflow appropriate to its exact stage and change. Invocation SHALL use syntax verified for that provider CLI/version; mini me SHALL NOT substitute a free-form programming prompt, invoke a guessed OpenSpec shell command, or treat `openspec validate` as agent workflow execution. Stage profiles SHALL be independent and capability-validated. CONTRACT REVIEW SHALL be read-only and SHALL NOT authorize APPLY, final code review, product decisions, or merge. Any VERIFY/E2E mutation of tracked candidate content SHALL be treated as substantive authorship and require candidate refreezing plus renewed reviewer-independence evaluation.

#### Scenario: Native workflow invocation is observed
- **GIVEN** an authorized APPLY dispatch with an installed compatible provider workflow
- **WHEN** the provider agent executes the change
- **THEN** evidence identifies the actual CLI/version, workflow or skill loaded, exact change and worktree, invocation result, and observed resulting artifacts/diff
- **AND** the evidence is corroborated by tool/process observation and repository state, not solely by agent-authored transcript text.

#### Scenario: R01 stage roles are applied without collapsing review gates
- **GIVEN** the configured R01 stage profiles and compatible installed workflows
- **WHEN** the run reaches PLAN, CONTRACT REVIEW, APPLY, implementation TEST, VERIFY/E2E, and final REVIEW
- **THEN** Codex handles PLAN and VERIFY/E2E, AGY handles APPLY and implementation TEST, DeepSeek is preferred only for explicitly authorized read-only CONTRACT REVIEW with AGY as its alternative, and final REVIEW remains governed by separate author-independence rules
- **AND** contract-review evidence cannot authorize APPLY, final REVIEW, or human merge.

#### Scenario: Contract review has no eligible authorized provider
- **GIVEN** DeepSeek is unavailable, incompatible, has unknown/stale/exhausted capacity, or lacks explicit stage/budget authorization, and AGY is also ineligible
- **WHEN** the run reaches CONTRACT REVIEW
- **THEN** mini me preserves the Change and waits without inference or proceeding to APPLY.

#### Scenario: Native workflow is unavailable or unproven
- **GIVEN** the requested workflow is absent, incompatible, or cannot be proven to have executed
- **WHEN** APPLY is requested or returns
- **THEN** mini me blocks or classifies the result as insufficient evidence
- **AND** does not claim successful OpenSpec application or create a successful candidate record.

#### Scenario: Adversarial apply: free-form programming prompt substitution rejection
- **GIVEN** an implementer dispatch configuration or request attempting to pass synthetic coding instructions, prompt-emulated task markdown, or raw source diffs instead of the installed native `openspec-apply-change` workflow
- **WHEN** execution pipeline preflight validates the dispatch payload
- **THEN** mini me rejects the request as a prompt-emulation violation
- **AND** refuses to invoke the provider CLI or record an implementation attempt.

#### Scenario: Adversarial apply: unverified or incompatible OpenSpec skill version rejection
- **GIVEN** the installed provider OpenSpec skill or CLI version does not match the repository's required capability version or fails cryptographic hash verification
- **WHEN** NativeOpenSpecApplyResolver validates the execution environment
- **THEN** mini me blocks dispatch with an explicit incompatible workflow error
- **AND** records insufficient evidence without invoking paid provider inference.

#### Scenario: Adversarial apply: out-of-scope file modification or workspace breakout
- **GIVEN** an implementer agent attempt modifies files outside the authorized OpenSpec change scope or writes to paths outside the assigned worktree boundary
- **WHEN** candidate manifest verification evaluates the resulting changes
- **THEN** mini me rejects the candidate with a scope boundary violation
- **AND** halts stage advancement, discarding unauthorized mutations and keeping the candidate unverified.

### Requirement: R01-S04 Candidate and source changes remain bound to the owned worktree
The implementation SHALL remain within the exact authorized worktree and be bound to the original base SHA, current candidate SHA, generation, repository identity, and authoring attempt. Mini me SHALL observe real source changes and preserve uncommitted or committed candidate evidence across recoverable interruption; it SHALL NOT fabricate patches, commits, candidate files, task completion, or authorship. The candidate commit, candidate manifest, and published PR SHALL verifiably exclude generated compiler and runtime artifacts (`__pycache__`, `*.pyc`, `*.pyo`, `.pytest_cache`); check executions SHALL NOT contaminate the candidate worktree with uncommitted or tracked bytecode.

#### Scenario: Real candidate is observed
- **GIVEN** a native APPLY run that changes fixture source files
- **WHEN** the stage returns
- **THEN** mini me records the actual diff/manifest and observed candidate SHA against the bound base
- **AND** verifies all changed paths are inside the assigned worktree and within the approved change scope.

#### Scenario: Generated compiler and runtime artifacts are strictly excluded
- **GIVEN** a native APPLY execution completes and prepares a candidate manifest or candidate commit
- **WHEN** mini me inspects candidate changes and computes the candidate manifest
- **THEN** it strictly excludes bytecode and runtime caches (`__pycache__`, `*.pyc`, `*.pyo`, `.pytest_cache`) from the manifest and candidate ref
- **AND** published branches and Draft PRs contain only approved source modifications without compiled Python bytecode.

#### Scenario: Candidate with tracked or staged generated artifacts is rejected
- **GIVEN** an implementer attempt or worktree mutation stages or commits `.pyc` or `__pycache__` artifacts into git tracking
- **WHEN** candidate manifest verification or candidate freeze executes
- **THEN** mini me rejects the candidate with a structured validation error
- **AND** fails closed before checks, review, branch push, or PR creation.

#### Scenario: Check execution regression prevents worktree contamination
- **GIVEN** configured deterministic checks or test runners execute against the candidate worktree
- **WHEN** the check runner runs test suites (such as pytest)
- **THEN** bytecode generation is isolated (via `PYTHONPYCACHEPREFIX` or equivalent execution isolation) so no uncommitted or untracked cache diffs remain in the worktree
- **AND** post-check git status confirms the working tree remains clean and byte-for-byte identical to the candidate manifest.

#### Scenario: Non-destructive remediation of transient generated artifacts
- **GIVEN** transient untracked bytecode or cache artifacts pollute a candidate worktree after diagnostic or check execution
- **WHEN** candidate remediation or re-verification is performed for that worktree
- **THEN** mini me safely purges the transient generated artifacts without modifying the frozen candidate commit, altering the base SHA, or invalidating durable attempt and event lineage
- **AND** the verified clean worktree is matched against the durable candidate manifest.

#### Scenario: Interrupted apply preserves candidate evidence
- **GIVEN** an APPLY process is interrupted after a material diff but before stage acknowledgment
- **WHEN** the same durable Run/Job is recovered
- **THEN** mini me reconciles the existing worktree, diff, and checkpoint before any retry
- **AND** neither discards material work nor creates a duplicate execution identity.

#### Scenario: Frozen candidate remediation reuses its existing worktree
- **GIVEN** the Run and Job reference the same frozen candidate SHA and generation, with a matching durable candidate manifest and a physically present worktree whose ownership is `CREATED`
- **WHEN** the same Run/Job re-enters implementation for an authorized review or audit remediation
- **THEN** mini me verifies the repository binding, ownership marker, branch, original base SHA, candidate ref/HEAD, generation, manifest, and clean observed worktree state before reusing that exact path
- **AND** it preserves the worktree rather than routing the candidate through candidate-free recovery or removing it before remediation can resume.

#### Scenario: Candidate worktree ownership is absent, deleted, or contradictory
- **GIVEN** candidate evidence exists but the worktree is absent, ownership is not `CREATED`, or Run/Job/ownership/manifest/Git evidence disagrees
- **WHEN** worktree reuse is requested
- **THEN** mini me fails closed without recreating from the current base, overwriting local state, or changing candidate evidence.

#### Scenario: Adversarial candidate manipulation: tampering with candidate commit SHA, out-of-bounds additions, or forged manifest hash
- **GIVEN** an external process, rogue tool, or adversarial script modifies files in the candidate worktree, alters git HEAD directly, or supplies a forged candidate manifest hash
- **WHEN** CandidateManifestService or pre-review verification executes
- **THEN** mini me detects the hash and HEAD discrepancy against the durable candidate record
- **AND** rejects progression, failing closed before checks or review without altering durable lineage.

#### Scenario: Adversarial recovery: poisoned fence token, corrupted checkpoint replay, or mid-attempt crash with uncommitted modifications
- **GIVEN** a daemon crash occurs mid-execution leaving uncommitted dirty files in the worktree, or a replay request supplies an invalid, expired, or mismatched fence token
- **WHEN** recovery and resume reconciliation execute
- **THEN** mini me validates the fence token and worktree state, rejects the poisoned or stale token, and reconciles observed uncommitted progress safely without duplicate stage execution or lost work.

### Requirement: R01-S05 Checks and independent review govern candidate progression
Mini me SHALL run the repository's configured deterministic implementation tests and applicable installed OpenSpec verification workflow against the exact candidate using the configured stage profiles; R01 assigns implementation TEST to AGY and VERIFY/E2E to Codex, subject to actual CLI/model/effort capability validation. Authoritative final review SHALL be read-only, bound to the frozen repository identity, candidate SHA, base SHA, generation, manifest, and surviving authorship, and performed by an identity distinct from every substantive author whose changes survive in that candidate. An eligible complementary primary is the normal final reviewer. DeepSeek Direct MAY satisfy final code review only under the pre-existing narrow fallback condition that no eligible primary reviewer can serve and only under an explicitly authorized, compatible, distinct read-only reviewer contract with complete candidate-bound input and a structured response accepted by deterministic validation. R01's DeepSeek-preferred CONTRACT REVIEW is a separate pre-APPLY stage and SHALL NOT count as final review. The existing DeepSeek audit runner or audit result SHALL NOT be converted into review evidence. If no final reviewer path is available and authorized, the candidate SHALL remain preserved in a truthful waiting state; no review result SHALL authorize human merge.

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

#### Scenario: DeepSeek final-review fallback is explicitly authorized and independently validated
- **GIVEN** no eligible primary reviewer can serve the frozen candidate and a compatible DeepSeek read-only review integration, sufficient review input, exact candidate binding, and explicit per-stage provider and budget authorization are verified
- **WHEN** DeepSeek Direct reviews the candidate under the distinct reviewer contract
- **THEN** the system validates a structured response deterministically, records review evidence bound to repository/base/head/generation/manifest and reviewer identity, and may satisfy the review gate only if the reviewer is distinct from all surviving substantive authors
- **AND** it does not derive approval from an audit record, omit required candidate context, or authorize human merge.

#### Scenario: DeepSeek final-review fallback is unavailable, incompatible, or unauthorized
- **GIVEN** no eligible primary reviewer can serve and DeepSeek compatibility, sufficient input, explicit provider authorization, or stage budget is absent or uncertain
- **WHEN** the pipeline evaluates review eligibility
- **THEN** it does not invoke DeepSeek, does not treat audit evidence as review, preserves the candidate, and remains in a truthful waiting or blocked state.

#### Scenario: Contract-review evidence cannot satisfy final review
- **GIVEN** a valid DeepSeek or AGY CONTRACT REVIEW result exists for the OpenSpec artifacts but no valid candidate-bound final code review exists
- **WHEN** the candidate approaches PR readiness
- **THEN** mini me preserves the candidate and requires a separate final reviewer that is independent from all surviving substantive authors
- **AND** the contract-review record is not reused or relabeled as final-review evidence.

#### Scenario: Optional audit is not silently required or invoked
- **GIVEN** primary review and all required checks pass, with no explicit policy or human authorization requiring an independent fallback audit
- **WHEN** the candidate approaches the human PR gate
- **THEN** mini me does not require or silently invoke DeepSeek/OpenRouter audit
- **AND** any fallback audit is dispatched only after dual-primary unavailability, compatible tool capability, explicit authorization, and applicable budget approval.

#### Scenario: Adversarial review: self-review attempt via alias, altered author metadata, or surviving contributions
- **GIVEN** an author attempts to review their own candidate changes using an alternate model identifier, pseudonym, or alias, or a candidate where their contributions survive from a prior attempt
- **WHEN** ModelIdentityService and AuthorshipService evaluate reviewer eligibility
- **THEN** mini me detects surviving substantive authorship and rejects the authoritative review with an explicit policy violation
- **AND** blocks PR progression until an independent reviewer evaluates the candidate.

#### Scenario: Adversarial review: audit substitution or fabricated structured review payload
- **GIVEN** a request attempts to substitute an existing DeepSeek audit result, a forged approval token, or an unverified free-form text response as authoritative review evidence
- **WHEN** review authority validation executes
- **THEN** mini me rejects the payload as an invalid review authority
- **AND** enforces strict structured schema validation, preventing unproven advancement.

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

#### Scenario: Adversarial PR delivery: conflicting remote branch ref or target branch mutation
- **GIVEN** the remote tracking branch has advanced independently, diverged from the local candidate branch, or targets a protected production branch instead of the authorized fixture PR branch
- **WHEN** PR reconciliation or git push pre-flight executes
- **THEN** mini me aborts the push operation immediately
- **AND** refuses to force-push, rewrite remote history, or mutate unauthorized target branches.

#### Scenario: Adversarial PR delivery: automated merge attempt or non-human bypass rejection
- **GIVEN** an external tool, automation script, or agent attempts to invoke a merge command or bypass the human review gate
- **WHEN** orchestration stage progression is evaluated
- **THEN** mini me terminates progression at READY_FOR_HUMAN_MERGE
- **AND** blocks any automated merge or deployment action, requiring explicit human intervention.

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

#### Scenario: Adversarial N01 preservation: dispatch targeting N01 database or worktree fails closed
- **GIVEN** an execution request or environment variable incorrectly points the repository root, worktree path, or database connection to the protected production N01 instance
- **WHEN** ManagedWorkspaceGuard and admission binding validation execute
- **THEN** mini me detects the protected N01 identity and halts immediately
- **AND** refuses to create worktrees, acquire locks, or run migrations against N01 state.

#### Scenario: Adversarial N01 preservation: state hash discrepancy fails verification
- **GIVEN** a post-fixture verification step detects any divergence in the read-only hash of N01 runs, jobs, attempts, events, or worktrees
- **WHEN** N01 preservation assertion executes
- **THEN** verification fails closed with a severe integrity violation
- **AND** reports the exact discrepancy without attempting automated repair or mutation of N01.

### Requirement: R01-E01 Real end-to-end delivery in an authorized fixture
R01 acceptance SHALL include an externally observable, bounded end-to-end run using a small authorized disposable GitHub repository, a real READY OpenSpec change created through agent-side OpenSpec, the approved stage profiles and compatible real agents, real Git operations, deterministic checks, separate contract and final review evidence, and a real Draft PR. Test doubles MAY cover isolated contracts only and SHALL NOT satisfy this product acceptance scenario.

#### Scenario: Real fixture change reaches a reviewable PR
- **GIVEN** an authorized disposable repository with a bound READY change covering success, rejection, and regression behavior, configured checks, independently validated stage profiles, explicit per-stage budget, and capacity for the next required stage
- **WHEN** the operator authorizes one bounded delivery run through the real API/CLI path
- **THEN** the real agents execute the assigned native workflows (Codex PLAN/VERIFY-E2E; AGY APPLY/implementation TEST; DeepSeek-preferred authorized read-only CONTRACT REVIEW with AGY alternative; final REVIEW under the separate independence policy) and create a functional source change only in the owned worktree
- **AND** contract-review evidence does not authorize APPLY or satisfy final review, checks pass, an independent final reviewer evaluates the frozen candidate, and a real Draft PR is observable at the exact candidate SHA with zero committed bytecode or runtime cache artifacts.

### Requirement: R01-E02 Provider workflow identity is proven
R01 SHALL demonstrate actual native workflow loading for the assigned Codex and AGY stages and any review provider actually used; provider/model/effort/workflow support SHALL be observed against each exact installed CLI/version, not assumed interchangeable. Historical Codex APPLY evidence does not replace proof of the revised AGY APPLY assignment.

#### Scenario: Assigned provider workflows and profiles are proven
- **GIVEN** the authorized R01 fixture, exact installed Codex/AGY CLI versions, and configured model/effort profiles
- **WHEN** Codex executes PLAN or VERIFY/E2E and AGY executes APPLY or implementation TEST
- **THEN** process/tool evidence proves each CLI loaded the supported native OpenSpec workflow for its exact stage/change and the configured model/effort were supported
- **AND** generic text instructions, shell-only validation, or another provider's trace do not satisfy the proof.

#### Scenario: Unsupported model or effort blocks the stage
- **GIVEN** the configured model or effort is unsupported or unobservable for the exact installed CLI/version
- **WHEN** the stage profile is resolved
- **THEN** mini me blocks before inference rather than substituting an assumed default or marking the workflow proof complete.

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
