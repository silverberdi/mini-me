## ADDED Requirements

### Requirement: Bounded SRE Unblocker invocation
When an active Run is paused or reaches `HUMAN_REQUIRED` for a technical precondition, mapping, or heuristic ambiguity, the existing Watchdog/orchestration flow SHALL invoke the configured SRE Unblocker role only when the cause is within an explicitly allowlisted, deterministic technical recovery and evidence binds the action to the current Run, stage, candidate, and authorized scope. The Unblocker SHALL use existing native workflows, CLI commands, and recovery authorities, record its action and observed result, and SHALL NOT answer or bypass human authorizations for product/scope decisions, security, exceptional cost, destructive or irreversible actions, implementation merge, or any ambiguous cause. If eligibility or success cannot be proven, the Run SHALL retain the current human-gate question and options.

#### Scenario: Eligible technical blocker is resolved
- **WHEN** the Watchdog identifies a technical blocker covered by an allowlisted idempotent recovery and the Run/candidate evidence is current
- **THEN** it invokes the configured SRE Unblocker role through the existing orchestration authority
- **AND** the recovery result is observed and the same Run resumes only through its canonical lifecycle transition

#### Scenario: Unblocker cannot establish a safe technical cause
- **WHEN** evidence is missing, conflicting, outside the allowlist, or the proposed action could change product scope, security, exceptional spend, or irreversible state
- **THEN** the Unblocker performs no action
- **AND** the existing human gate presents the current question, cause, evidence, and available options

#### Scenario: Recovery action fails or does not remove the blocker
- **WHEN** an eligible action fails or its result does not prove that the blocker is resolved
- **THEN** the system records the attempted action and observed failure
- **AND** stops further autonomous attempts for that blocker and escalates through the existing human-gate authority

#### Scenario: PF-03 fallback warning is proven non-blocking
- **WHEN** a PF-03 fallback/precondition warning is backed by local evidence that the fallback is applied and non-blocking, and its required verification scenario is mapped and verified
- **THEN** the Unblocker records the evidence and allows the existing feasibility authority to continue
- **AND** it does not dismiss an unmet required precondition, an unmapped check, or missing CI identity as cosmetic

#### Scenario: MCP OAuth 401 has a configured refresh path
- **WHEN** an MCP connection reports an authentication 401, is configured for OAuth, and the existing credential service confirms a renewable refresh token without exposing credential values
- **THEN** the Unblocker requests renewal through the existing OAuth credential service
- **AND** retries an MCP operation only when evidence proves the rejected request had no effect and the operation is safe to repeat
- **AND** repeatability is proven by the discovered tool metadata explicitly setting `readOnlyHint: true` or `idempotentHint: true`, with `destructiveHint` not set to `true`
- **AND** when that metadata is absent, conflicting, or destructive, it stores the renewed credential but does not replay the operation and escalates with the original gate intact
- **AND** records success or failure without logging tokens

#### Scenario: OAuth refresh is unavailable or fails
- **WHEN** the MCP connection has no usable refresh token/configuration or the provider rejects renewal
- **THEN** the Unblocker does not substitute credentials or retry the protected operation
- **AND** it preserves the failure evidence and escalates through the current human-gate path

#### Scenario: Stale lock is proven to be orphaned
- **WHEN** the lock is inside the exact Run-owned worktree, the candidate SHA and durable ownership match, and the owning process is proven absent
- **THEN** the Unblocker delegates lock removal to the existing managed-worktree recovery authority
- **AND** records the lock digest and observed result without removing files outside the managed worktree

#### Scenario: Business, cost, or scope gate is escalated
- **WHEN** the current gate asks for a business, cost, or product-scope decision
- **THEN** the system preserves the original OpenSpec question text and original options exactly as received
- **AND** attaches the Unblocker's technical diagnosis separately without replacing, paraphrasing, or reordering the original question or options
- **AND** waits for the operator's decision

### Requirement: Immutable intervention evidence
Every SRE Unblocker invocation SHALL append an immutable PostgreSQL intervention fact with timestamp, project, run, stage, trigger, action, observed result, autonomous/operator outcome, root-cause classification, and any supported improvement reference. Replaying the same event identity SHALL be idempotent; later diagnosis or resolution SHALL be represented by a new fact rather than rewriting the prior record. The record SHALL not contain secrets or unrelated project data.

#### Scenario: Intervention fact is retained
- **WHEN** the Unblocker attempts or completes an action
- **THEN** the system appends a sanitized intervention record linked to the exact Run and stage
- **AND** the record remains unchanged when a later event records resolution or escalation

#### Scenario: Duplicate delivery of the same intervention event
- **WHEN** orchestration retries persistence for an intervention event already recorded
- **THEN** the event identity prevents a duplicate record
- **AND** the original timestamp and evidence remain intact
