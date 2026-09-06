# Proposal: Generic Provider Capacity Recovery & Drain Policy

## Problem Statement
Description / Functional Requirements:

Implement a provider-agnostic capacity recovery and drain policy for mini me.

The goal is to ensure that temporary provider unavailability is handled through
a generic provider capability model rather than hardcoded logic for Codex,
Antigravity, OpenRouter, or any specific current provider.

The design must support current providers and future replacements such as Cursor
or other execution providers without requiring scheduler/lifecycle rewrites.

The policy must distinguish clearly between:

1. provider health/capacity recovery;
2. waiting for the primary execution provider;
3. operator-supplied expected return time;
4. drain/finalization fallback for work already materially in progress.

OpenRouter remains a drain/finalization provider only. It must never be used to
start new work solely because the primary provider is unavailable.

============================================================
GENERIC PROVIDER CAPABILITY CONTRACT
============================================================

Introduce or formalize a provider abstraction capable of exposing, where
supported:

- provider identity
- provider role/capabilities
- health status
- capacity status
- unavailability reason
- probe capability
- expected reset discovery capability
- expected reset time
- reset source
- last probe time
- next probe time
- drain/fallback eligibility

The scheduler and orchestration lifecycle must depend on the generic contract,
not provider-specific branching.

Provider-specific logic belongs only in provider adapters.

Examples:

- Codex adapter
- Antigravity adapter
- OpenRouter adapter
- DeepSeek adapter where relevant
- future Cursor adapter
- test/fake provider adapter

Do not introduce logic such as:

if provider == "codex"

inside generic scheduler/lifecycle policy.

============================================================
PROVIDER RECOVERY PROBING
============================================================

Any provider marked temporarily unavailable must be periodically re-evaluated.

Provider probes must:

- not create Runs;
- not create Jobs;
- not consume implementation retry budget;
- not start backlog work;
- not execute a full implementation task;
- remain lightweight and bounded.

Positive probe:
temporarily_unavailable -> available

Negative probe:
remain temporarily_unavailable and persist fresh evidence.

Persist at minimum:

- provider_status
- capacity_reason
- waiting_since where relevant
- last_probe_at
- next_probe_at
- expected_reset_at when known
- reset_source when known

Supported reset sources:

- AUTO_DISCOVERED
- OPERATOR_REPORTED

If a provider cannot expose reset timing, expected_reset_at remains unknown until
the operator provides it or the provider later exposes reliable evidence.

============================================================
KNOWN RETURN TIME
============================================================

If mini me has sufficiently reliable expected_reset_at:

- wait automatically for the primary provider;
- continue bounded periodic probes;
- avoid wasteful high-frequency probes;
- probe promptly at/after expected reset;
- recover automatically if provider becomes available earlier;
- allow the operator to choose drain/finalization fallback for eligible
  in-progress work.

============================================================
UNKNOWN RETURN TIME
============================================================

If expected_reset_at is unknown:

- enter WAITING_CAPACITY;
- continue bounded provider probes;
- do not consume implementation retry budget;
- after a maximum blind automatic wait of 2 hours, surface an explicit operator
  decision.

Required operator choices:

1. Set expected provider return date/time
2. Finish current in-progress work using configured drain provider
3. Keep waiting

Keep Waiting must:

- remain explicit operator intent;
- continue periodic probes;
- preserve the option to change decision later;
- not silently consume retry budget;
- not become invisible indefinite waiting.

============================================================
OPERATOR-REPORTED RESET
============================================================

The operator may provide or update expected_reset_at.

Persist:

reset_source = OPERATOR_REPORTED

Provider probes remain authoritative for actual recovery.

If the provider recovers before the operator-reported time:
mini me resumes automatically where safe.

============================================================
DRAIN POLICY
============================================================

Drain/fallback policy applies ONLY to work already materially in progress.

Eligibility requires:

- active orchestration run;
- material execution already started;
- primary execution provider unavailable;
- configured drain provider available and permitted by policy.

It does NOT apply to:

- BACKLOG
- READY
- QUEUED
- work with no material execution attempt
- newly admitted work with no provider work started

Those items must remain waiting for the primary execution provider.

============================================================
MATERIAL EXECUTION
============================================================

Define one canonical backend-owned rule for material_execution_started.

Examples may include:

- provider attempt actually started;
- worktree contains provider-produced material changes;
- candidate material/evidence exists.

Do not let frontend determine eligibility.

============================================================
DRAIN PROVIDER
============================================================

The drain provider must be configured generically.

Current expected configuration may use OpenRouter, but the lifecycle must not
hardcode OpenRouter as the only possible drain provider.

The drain provider receives a structured handoff containing:

- current Run/Job identity;
- existing attempt/candidate context;
- worktree state;
- valid material already produced;
- remaining work only;
- acceptance criteria;
- relevant failure/capacity evidence.

The drain provider must not unnecessarily restart the task from zero.

After drain implementation:
normal lifecycle continues:

candidate
-> checks
-> independent review
-> DeepSeek audit
-> PR
-> human merge gate
-> native post-merge closure

============================================================
PROVIDER ROLES
============================================================

Preserve current provider governance.

Routine primary execution provider:
configured by provider policy.

Premium/review provider:
configured by provider policy.

Independent auditor:
configured by provider policy.

Drain provider:
configured independently for finishing eligible in-progress work.

Do not conflate these roles.

============================================================
PWA / TUI OPERATOR EXPERIENCE
============================================================

When work is waiting on provider capacity, expose:

- primary provider
- provider status
- exact capacity/unavailability reason when known
- waiting_since
- last_probe_at
- next_probe_at
- expected_reset_at
- reset_source
- material execution started: YES/NO
- drain eligible: YES/NO
- configured drain provider
- retry budget consumed

If drain is eligible, expose:

- Wait for primary provider
- Finish current work with drain provider
- Set/Change expected return time

If drain is NOT eligible, clearly explain why.

Example:

Primary provider unavailable
Work has not started
Drain eligible: NO
Reason: drain policy only applies to materially in-progress work.

============================================================
PROVIDER REPLACEMENT SAFETY
============================================================

Prove that scheduler/lifecycle behavior does not depend on Codex or
Antigravity-specific conditionals.

Add tests demonstrating the same recovery policy using:

- Codex adapter
- Antigravity adapter
- fake/test provider

The fake provider should prove that a future provider such as Cursor can
participate without changing generic scheduler/orchestration logic.

============================================================
IDEMPOTENCY / SAFETY
============================================================

Required:

- provider probes do not create duplicate Runs/Jobs;
- recovery does not create duplicate attempts;
- drain handoff does not create a new backlog item;
- drain handoff does not create a duplicate Run;
- repeated operator decisions are idempotent where applicable;
- stale operator mutation fails safely;
- provider status transitions are auditable.

============================================================
NO SCOPE CREEP
============================================================

Do NOT implement:

- Cursor integration itself;
- new provider UI marketplace;
- secret management;
- new provider billing logic;
- arbitrary provider switching for new work;
- generalized autonomous provider selection beyond existing policy;
- multi-provider parallel implementation.

This item creates the generic capability boundary only.

## Proposed Change
Deliver the capabilities and requirements defined for `generic-provider-capacity-recovery-drain`.

## Acceptance Criteria
- ============================================================
- ACCEPTANCE CRITERIA
- ============================================================
- Scheduler contains no Codex-specific recovery branching
- Scheduler contains no Antigravity-specific recovery branching
- Provider-specific recovery behavior is isolated behind provider adapters
- Codex temporarily_unavailable is periodically re-probed
- Antigravity temporarily_unavailable is periodically re-probed
- Fake/test provider uses the same generic recovery path
- Positive probe transitions provider to available automatically
- Negative probe preserves temporarily_unavailable with fresh evidence
- Provider probes create 0 Runs
- Provider probes create 0 Jobs
- Provider probes consume 0 implementation retry budget
- Known expected reset is persisted and visible
- AUTO_DISCOVERED reset source is supported
- OPERATOR_REPORTED reset source is supported
- Operator can enter or update expected provider return time
- Unknown reset can enter bounded WAITING_CAPACITY
- Blind automatic wait is bounded to 2 hours
- After blind-wait threshold explicit operator decisions are surfaced
- Keep Waiting does not consume implementation retry budget
- Drain provider never starts BACKLOG work
- Drain provider never starts READY work
- Drain provider never starts QUEUED not-yet-started work
- Drain eligibility requires material execution already started
- Drain handoff preserves valid existing work and evidence
- Drain handoff continues the same Run/Job lifecycle
- Drain does not create duplicate Run/Job/backlog item
- Original provider recovery can resume waiting work automatically when safe
- PWA exposes provider status, reason, wait timing, probes, reset and drain eligibility
- TUI exposes equivalent provider-capacity state
- PWA, TUI and PostgreSQL agree
- Provider recovery and operator decisions are auditable
- Current Codex behavior works through generic provider contract
- Current Antigravity behavior works through generic provider contract
- Future provider replacement requires adapter implementation, not scheduler rewrite
- Real production validation demonstrates recovery without human provider-state repair

## Non-Goals
- Opportunistic refactoring outside the defined acceptance criteria.
- Undocumented scope changes or speculative features.

## Capabilities
- `generic-provider-capacity-recovery-drain-policy`: Generic Provider Capacity Recovery & Drain Policy
