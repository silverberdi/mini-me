# Design: Preserved Candidate Remediation Generations

## Source of Authority
The source candidate MUST be the latest non-superseded `OrchestrationCandidate`.

Before remediation:
- `run.current_generation == source_candidate.generation`
- `run.current_candidate_sha == source_candidate.candidate_sha`
- `job.candidate_sha == source_candidate.candidate_sha`
- `job.base_sha == source_candidate.base_sha`

`run.base_sha` remains historical admission evidence and is not rewritten.

## Eligibility
Remediation is allowed only when run/job/candidate/manifest/Git authority agrees and the run is at
`NEEDS_HUMAN`. Any ambiguity fails closed.

## Explicit Human Operation
Add an explicit operation conceptually equivalent to:

`minime orchestrate resolve <run_id> --remediate-preserved-candidate --contract <file> --path <root>`

Do not overload `--continue-preserved-candidate`.

## Immutable Remediation Contract
Minimum structured fields:
- contract_version
- run_id
- source_candidate_generation
- source_candidate_sha
- source_candidate_base_sha
- change_name
- objective
- allowed_paths
- protected_paths
- required_outcomes
- verification_commands
- stop_conditions

The contract is parsed, validated, canonically serialized, SHA-256 hashed, persisted durably, and
bound to source identity. Changed paths MUST be a subset of `allowed_paths` and MUST NOT intersect
`protected_paths`.

## Persistence
Introduce a durable remediation request record with source identity, immutable contract hash/payload,
status, and resulting candidate identity. Its migration MUST extend the single current Alembic head.

## Generation Semantics
Source generation N produces N+1 from `source_candidate.candidate_sha`.
N is superseded only after N+1 durable authority is established. Historical commits/refs are never
rewritten.

## Managed Workspace
Create a new remediation branch/worktree such as:
`minime/<change>-<job>-remediation-gen<N+1>`

Never reuse or mutate the source candidate workspace.

If the registered base advanced, stop with `BASE_ADVANCED_REQUIRES_INTEGRATION`.

## Agent Boundary
The implementer receives the authoritative worktree, exact source identity, immutable contract/hash,
allowed/protected paths, required outcomes, and stop conditions.

If work outside the contract is required, it must stop with a structured blocker.

## Progress and Finalization
Progress is measured against source candidate SHA.
- NO_PROGRESS => no new generation.
- unauthorized change => `REMEDIATION_SCOPE_VIOLATION`, preserve workspace.
- mini me owns final commit creation.

## Manifest and Authority Persistence
After finalization, generate a new manifest, persist N+1, align Job/current run bindings, supersede N,
and persist remediation evidence. `run.base_sha` remains unchanged.

## Deterministic Checks
Run every configured check sequentially and persist evidence for every check.
Disposable PostgreSQL checks remain fail-closed but MUST NOT short-circuit later evidence collection.

## Check Failure
If N+1 checks fail, preserve N+1 as current, persist all evidence, stop `NEEDS_HUMAN`, classify as
`REMEDIATION_CHECKS_FAILED`, and do not revert to N.

## Error Taxonomy
At minimum:
- REMEDIATION_AUTHORITY_MISMATCH
- REMEDIATION_CONTRACT_INVALID
- REMEDIATION_SCOPE_VIOLATION
- REMEDIATION_NO_PROGRESS
- REMEDIATION_PROVIDER_UNAVAILABLE
- REMEDIATION_CHECKS_FAILED
- REMEDIATION_PRESERVATION_FAILED
- BASE_ADVANCED_REQUIRES_INTEGRATION
- BASE_INTEGRATION_CONFLICT

## Idempotency
Identity includes run_id + source_generation + source_candidate_sha + contract_hash.
Replay never duplicates completed agent work or candidate generations.

## Restart Safety
Recovery must be safe across contract/workspace/agent/commit/manifest/candidate/check boundaries.
Dirty worktrees are never force-deleted.

## Review/Audit Isolation
Evidence from generation N never satisfies N+1.

## Architectural Boundary
Do NOT grow `resolve_preserved_candidate()` into a larger monolith.
Use a dedicated remediation service/component. OrchestrationService coordinates; WorktreeManager owns
Git mechanics; ChecksRunner owns checks; repositories/UoW own persistence.

## Migration Rule
Exactly one Alembic head before and after implementation. No merge migration to hide accidental
branching. Offline PostgreSQL `upgrade head --sql` must succeed.

## End-to-End Acceptance
Real-Git E2E must prove:
N -> NEEDS_HUMAN -> explicit contract -> managed remediation worktree -> bounded change ->
system finalization -> N+1 -> manifest -> all checks -> next-gate eligibility.

A second E2E must prove:
N+1 checks fail -> N+1 remains preserved/current -> later explicit remediation -> N+2,
without mutating N or N+1.
