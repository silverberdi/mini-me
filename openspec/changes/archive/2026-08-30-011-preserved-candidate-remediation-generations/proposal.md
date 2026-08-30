# Proposal: Preserved Candidate Remediation Generations

## Why

mini me can preserve immutable candidate generations, reconstruct/adopt historical candidates,
integrate them onto an advanced base, and bind deterministic checks to candidate SHA/generation.

However, when an integrated preserved candidate fails deterministic checks and the run stops at
`NEEDS_HUMAN`, mini me has no supported authority-preserving operation to remediate that frozen
candidate.

The current unsafe alternatives are unacceptable:

- editing a frozen candidate worktree directly;
- mutating a frozen candidate commit;
- rewriting historical candidate rows;
- manually changing job/run bindings;
- manually inventing a new candidate outside mini me;
- restarting broad implementation without a bounded remediation contract.

This gap is demonstrated by the preserved generation-2 candidate of
`010-governance-and-recovery-hardening`.

This companion change is required before change 010 can be remediated safely.

## What Changes

This change adds a generic preserved-candidate remediation capability that:

- requires explicit human authorization;
- uses the latest valid `OrchestrationCandidate` as current candidate authority;
- persists a structured immutable remediation execution contract;
- binds the contract to exact run/generation/source candidate identity;
- creates a new managed remediation branch/worktree from the frozen candidate SHA;
- constrains implementer edits through machine-verifiable allowed/protected paths;
- prevents the implementer from redefining the remediation contract;
- measures progress against the source candidate;
- lets mini me, not the agent, finalize the authoritative candidate commit;
- creates monotonic immutable candidate generations N+1, N+2, etc.;
- generates a new manifest for each resulting generation;
- executes and persists every configured deterministic check;
- preserves failed remediation generations instead of rewriting or deleting them;
- separates remediation/check failures from Git base-integration conflicts;
- preserves `run.base_sha` as historical admission evidence;
- keeps review and audit evidence generation-specific;
- provides restart-safe and idempotent remediation;
- introduces a dedicated remediation service instead of expanding
  `resolve_preserved_candidate()` into a recovery monolith;
- adds real-Git end-to-end acceptance for successful and failed remediation generations.

This change does NOT implement the functional remediation of change 010 itself.
It provides the infrastructure required to do so safely afterward.

## Capabilities

### New Capabilities

- `preserved-candidate-remediation`
  - explicit human-authorized remediation of a frozen current candidate;
  - immutable remediation execution contracts;
  - scope-constrained agent execution;
  - monotonic candidate remediation generations;
  - remediation restart/idempotency guarantees;
  - complete candidate-bound deterministic-check evidence.

### Modified Capabilities

None.

## Impact

Expected implementation impact includes:

- orchestration CLI and coordination;
- a dedicated candidate remediation service/component;
- domain models for remediation contracts and durable remediation requests;
- persistence repositories/UoW integration;
- one Alembic migration extending the single current head;
- managed Git worktree/branch orchestration;
- implementer execution context;
- candidate manifest/generation persistence;
- deterministic check execution and evidence;
- status/observability;
- real-Git recovery acceptance tests.

Change `010-governance-and-recovery-hardening` artifacts are protected and MUST remain untouched by
implementation of this companion change.

Archived OpenSpec changes are also protected.

## Architectural Principles

1. Historical evidence is immutable.
2. Candidate generation is monotonic.
3. Candidate identity comes from durable state plus verified Git state.
4. Human authorization is explicit.
5. The remediation contract is data, not an informal prompt.
6. The implementer executes the contract; it does not redesign it.
7. Scope enforcement is machine-verifiable.
8. Failed work is preserved before cleanup.
9. Every deterministic check produces evidence.
10. Review and audit authority is generation-specific.
11. Replay MUST NOT duplicate generations.
12. `run.base_sha` remains historical admission evidence.
13. Current candidate authority comes from the latest valid `OrchestrationCandidate`.
