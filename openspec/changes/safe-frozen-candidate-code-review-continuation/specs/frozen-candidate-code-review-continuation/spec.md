## Purpose

Allows mini me to complete an independently authorized, read-only code review of a frozen candidate from a durable review hold without repeating implementation or checks, losing evidence, or bypassing the ordinary workflow's safety authorities.

## ADDED Requirements

### Requirement: Exact frozen-candidate review readiness
The system SHALL permit exceptional review-only continuation only for the active Run and Job whose project/change identity, generation, candidate SHA, base SHA, frozen candidate, manifest id/hash, managed repository binding, and owned worktree all agree. It SHALL validate the entire latest configured check batch for that candidate and generation, including exact check names and commands, unique membership, permitted timestamp spread, and passing exit codes. It SHALL preserve historical check records and SHALL NOT treat an empty configured check set or any isolated passing row as sufficient authority.

#### Scenario: Latest full passing batch follows an earlier failure
- **WHEN** the frozen candidate has an older failed batch and a later complete configured batch passes for the same SHA and generation
- **THEN** the latest batch authorizes review-only readiness, the older result remains queryable and unchanged, and current check status is reported as passed

#### Scenario: Current batch is partial, failed, or ambiguous
- **WHEN** the latest candidate-bound results omit a configured check, duplicate a check name, use a different command, exceed the allowed batch window, include a failure, or do not match the candidate SHA/generation
- **THEN** the system blocks review authorization and dispatch without invoking a reviewer

#### Scenario: Frozen candidate or repository identity disagrees
- **WHEN** Run, Job, project/change, repository binding, worktree ownership, candidate/base SHA, generation, manifest identity, or frozen status is absent or contradictory
- **THEN** the system fails closed before authorization consumption, reservation, or provider dispatch

### Requirement: Review-only continuation preserves execution boundaries
The system SHALL provide a single canonical, claim-fenced Control Plane path to dispatch only the independent DeepSeek Direct CODE_REVIEW for a ready frozen candidate. The path SHALL use current review-authority, provider capacity, account, model/effort, price, spending-policy, independence, and payload validation. It SHALL NOT invoke implementation, native APPLY, deterministic checks, audit, PR publication, merge, or scheduler work. A favorable review SHALL NOT authorize APPLY or merge.

#### Scenario: Valid exceptional review continuation
- **WHEN** the exact candidate is ready, fresh authorities pass, and the current Run claim/fence is valid
- **THEN** exactly the existing read-only DeepSeek CODE_REVIEW operation is dispatched for that candidate, with no APPLY or check execution

#### Scenario: Review approval remains a human gate
- **WHEN** DeepSeek returns READY_TO_MERGE for the exceptional pilot continuation
- **THEN** the review is durably completed and the candidate is preserved at the designated human gate without audit, PR, merge, or further execution side effects

#### Scenario: Review requests changes
- **WHEN** DeepSeek returns CHANGES_REQUIRED for the exceptional pilot continuation
- **THEN** findings are durably recorded and the candidate remains intact without automatic remediation under the one-shot authorization

#### Scenario: Ordinary autonomous Run retains its policy
- **WHEN** a non-exceptional Run reaches its normal independent-review stage under the owner's standing policy
- **THEN** it follows the existing autonomous continuation/remediation policy without a new per-call human authorization

### Requirement: One-shot review authority and direct-provider accounting
The system SHALL distinguish durable authorization from execution. Before any billed request on the exceptional path, it SHALL verify a current one-shot `AUTHORIZE_DEEPSEEK_CODE_REVIEW` authority bound to the same Run, Job, project/change, candidate/base SHA, generation, manifest id/hash, direct DeepSeek account, model/effort, verified price snapshot, expiry, and maximum spend. It SHALL link the authorization to one durable reservation and review checkpoint before dispatch, enforce the authorized bound and configured owner policy, and record only authentic provider usage/cost or explicit unresolved exposure. It SHALL NOT reuse OpenRouter authority, route a DeepSeek key through OpenRouter, substitute a reviewer/provider/model, or infer approval from a capacity or balance observation.

#### Scenario: Exact unexpired authorization is consumed once
- **WHEN** a matching unused authorization and current verified direct-account price/capacity evidence are present
- **THEN** the system durably links that action to one reservation and candidate-bound review before HTTP dispatch, and a duplicate request cannot create a second dispatch

#### Scenario: Missing or mismatched authority is rejected
- **WHEN** authorization is absent, expired, already consumed, over-bound, or differs in candidate, Run/Job, account, provider, model/effort, price snapshot, or billing origin
- **THEN** no reservation is spent and no provider request is made

#### Scenario: Usage or cost cannot be reconciled
- **WHEN** a provider response or transport outcome does not supply verifiable usage/cost evidence
- **THEN** the review and exposure remain explicitly unresolved/ambiguous under durable accounting policy, with no fabricated settlement or verdict

### Requirement: Fenced at-most-one dispatch and safe recovery
The system SHALL protect the slow review operation with the canonical Run claim, a single heartbeat owner, monotonic fence token, atomic pre-dispatch intent, and fenced result application. It SHALL persist sufficient review and dispatch checkpoints to resume validation/finalization without returning to implementation or checks. A timeout, crash, lost fence, concurrent request, or uncertain HTTP result after dispatch SHALL NOT trigger a blind repeat; absent proof that dispatch did not occur, the outcome SHALL remain ambiguous and the candidate and prior evidence SHALL be preserved.

#### Scenario: Concurrent continuation loses the claim
- **WHEN** another live owner holds the Run claim or the current worker loses/has a stale fence before dispatch or result application
- **THEN** the non-owner performs no provider dispatch or fenced state mutation

#### Scenario: Crash or timeout after dispatch intent
- **WHEN** process failure or timeout occurs after a durable dispatch intent is committed and provider effect is uncertain
- **THEN** recovery records or preserves an ambiguous checkpoint and does not automatically send the same billable review again

#### Scenario: Generic CONTINUE targets a review-authorization hold
- **WHEN** generic continuation is requested while the Run is stopped at `REVIEW_AUTHORIZATION_PENDING`
- **THEN** the request is rejected before changing Run stage, Job state, attempt count, candidate, or check evidence

### Requirement: Honest review and check state with preserved history
The system SHALL expose the current complete check-batch result separately from historical check rows and SHALL expose the exact review status, candidate identity, authorization/dispatch checkpoint, and human gate through existing operational projections. It SHALL retain all earlier check, review, action, reservation, candidate, attempt, and recovery evidence without rewriting it. Review completion SHALL be finalized through integrity validation under the current fence and SHALL NOT be left indefinitely `REVIEW_RUNNING` after a conclusively received and persisted verdict.

#### Scenario: Review result is durably finalized
- **WHEN** a valid structured review verdict is received and candidate integrity, spend reconciliation, and current fencing are verified
- **THEN** the same candidate-bound Review transitions to `REVIEW_COMPLETED`, findings/usage/events are queryable, and the projection reports the real review and current check states

#### Scenario: Historical failure is visible but not current
- **WHEN** a previous check row failed but the latest full configured batch passes for the same frozen candidate
- **THEN** the API/status projection reports current checks as passed while preserving and exposing the older failure as historical evidence

### Requirement: Pilot preservation and separately authorized post-deployment review
The system SHALL preserve the N01 Run, Job, candidate, manifest, authorship, worktree, attempts, prior reviews, checks, and accounting records during implementation and verification. It SHALL NOT run the N01 CODE_REVIEW as part of proposal, tests, or deployment. A real post-deployment N01 review SHALL require separate explicit authorization and fresh candidate, binding, claim, capacity, account, price, spending-policy, and budget validation. The same capability SHALL remain generic and SHALL NOT contain an N01 UUID-specific execution branch.

#### Scenario: Implementation and tests preserve N01
- **WHEN** the Change is applied and deterministic PostgreSQL/Git tests run in disposable environments
- **THEN** N01 identities and historical evidence remain unchanged and no production Run/Job/provider request is created

#### Scenario: Post-deployment review awaits a separate authorization
- **WHEN** the implementation is deployed but a separate explicit N01 review authorization has not been granted
- **THEN** no N01 review call is made and the work remains at its durable human/review gate

## Traceability

| Contract item | Requirement / scenario |
|---|---|
| FCR-01, FCR-03, FCR-04 | Exact frozen-candidate review readiness; first and second scenarios |
| FCR-02 | Review-only continuation preserves execution boundaries; first through third scenarios |
| FCR-05 | One-shot review authority and direct-provider accounting; second requirement scenarios |
| FCR-06 | One-shot review authority and direct-provider accounting; first and third scenarios; honest review state |
| FCR-07 | Fenced at-most-one dispatch and safe recovery |
| FCR-08 | Honest review and check state with preserved history |
| FCR-09 | Review-only boundary and pilot preservation |
| E01, E03 | Latest full passing batch after historical failure; successful review and historical projection |
| E02, E09 | Missing/mismatched authorization and provider identity rejected before call |
| E04 | Partial, failed, stale, or malformed latest batch blocked |
| E05 | Candidate/binding/worktree identity contradiction blocked |
| E06 | Claim loss, concurrency, crash, timeout, and uncertain dispatch recovery |
| E07, E08 | Pilot stop after either valid verdict |
| E10 | Generic CONTINUE denied before lifecycle mutation |
| E11 | Ordinary autonomous review flow preserved |
| E12 | Separate post-deployment authorization required; never run in this Change's proposal or tests |
