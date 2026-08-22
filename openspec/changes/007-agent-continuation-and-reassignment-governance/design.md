# Technical Design: 007 Agent Continuation and Reassignment Governance

## Context

During the implementation of change 006, multiple failure modes demonstrated the danger of trusting an AI agent's self-reported status:
1. **Premature Partial Delivery**: Executors repeatedly implemented partial work and stopped despite instructions to finish the entire change.
2. **False Blockers**: Executors claimed blockers based on imagined non-existent files (e.g. `scheduler_service.py`) when equivalent architectural integration points existed.
3. **Diminishing Returns on Corrective Prompts**: Issuing repeated corrective instructions to the same executor became unproductive compared to structured reassignment.
4. **Executor Takeover Loss**: Reassigning work risked discarding partial valid candidate progress.
5. **Reviewer Visibility Blindness**: Reviewers falsely reported missing test/code files because uncommitted or untracked candidate files were outside their initial view.
6. **Environment-Evidence Confusion**: Reviewers lacking local PostgreSQL daemon access reported integration test failures, confusing environmental inability with code defects.
7. **Mixed Authorship Integrity**: Multi-agent candidate authorship across attempts risked compromising reviewer independence.

mini me must establish an independent, deterministic execution governance layer. This layer operates strictly within the daemon core, evaluating verifiable evidence, validating blocker claims against declared contracts, generating structured handoffs on executor reassignment, proving candidate visibility for reviewers, and escalating deterministically to `NEEDS_HUMAN`.

See `proposal.md` for motivation and background context.

## Goals / Non-Goals

**Goals:**
- Implement a 4-layer state separation: Job Status, Attempt Outcome, Continuation Decision, and Evidence/Review Diagnostic.
- Implement a fully deterministic continuation engine based on explicit counters, signals, and hard ceilings.
- Implement fail-closed completion verification based on OpenSpec task states, git diffs, deterministic check results, and candidate commits.
- Implement a narrow, deterministic blocker validation service and deterministic blocker fingerprinting.
- Implement structured, restart-safe executor handoffs that preserve valid partial work in candidate worktrees.
- Implement anti-ping-pong boundaries and actionable `NEEDS_HUMAN` escalation.
- Implement pre-review candidate worktree manifests and reviewer visibility verification.
- Separate environmental execution inability (`ENVIRONMENT_UNAVAILABLE`, `REVIEW_ENVIRONMENT_INVALID`) from code implementation defects.
- Track candidate authorship across attempts, disclose mixed authorship on review reports, and enforce mandatory DeepSeek Direct independent audit and human merge.

**Non-Goals:**
- Autonomous code merge (human merge remains mandatory).
- Learned agent reputation or non-deterministic ML/LLM scoring models.
- LLM-based architectural inference during blocker validation.
- Arbitrary agent swapping outside configured project primary implementers and reviewers.
- Modifying provider budget and DRAIN fallback rules established in 005/006.
- Redesigning the web or TUI presentation layer.

## Decisions

### Decision 1: Four-Layer State & Diagnostic Separation

To prevent confusion between job lifecycle, executor outcomes, orchestration actions, and environmental diagnostics, the system establishes 4 distinct, orthogonal concepts:

| Layer | Responsibility | Possible Values |
| :--- | :--- | :--- |
| **Job Status** | Where the job is in the canonical lifecycle | `QUEUED`, `RUNNING`, `CHECKS_RUNNING`, `CHECKS_PASSED`, `REVIEW_RUNNING`, `AUDIT_RUNNING`, `READY_TO_MERGE`, `AUDIT_BLOCKED`, `CHANGES_REQUIRED`, `CHECKS_FAILED`, `WAITING_CAPACITY`, `NEEDS_HUMAN`, `FAILED`, `CANCELLED` |
| **Attempt Outcome** | What the executor attempt produced | `COMPLETED`, `CHANGES_REQUIRED`, `PREMATURE_STOP`, `FALSE_BLOCKER`, `REAL_BLOCKER`, `NO_PROGRESS`, `POLICY_VIOLATION`, `MALFORMED_RESULT`, `PROVIDER_FAILURE`, `PROVIDER_EXHAUSTED`, `ENVIRONMENT_UNAVAILABLE`, `EVIDENCE_INSUFFICIENT` |
| **Continuation Decision** | What orchestration will do next | `CONTINUE_SAME_AGENT`, `CORRECT_AND_RETRY`, `REASSIGN_AGENT`, `WAIT_EXTERNAL`, `NEEDS_HUMAN` |
| **Evidence / Review Diagnostic** | Quality/validity of a check or review execution | `PASS`, `FAIL`, `SKIPPED_BY_POLICY`, `ENVIRONMENT_UNAVAILABLE`, `EVIDENCE_NOT_REPRODUCIBLE`, `REVIEW_ENVIRONMENT_INVALID` |

`REVIEW_ENVIRONMENT_INVALID` is strictly an evidence diagnostic. When reviewer candidate visibility cannot be proven, the diagnostic is recorded as `REVIEW_ENVIRONMENT_INVALID`, prohibiting acceptance of authoritative review verdicts. The continuation engine decides `WAIT_EXTERNAL` (if environment repair/retry is possible) or `NEEDS_HUMAN` (if human intervention is required).

### Decision 2: Deterministic Inputs & Progress Classification

The continuation engine MUST NOT rely on qualitative assessments, semantic similarity, or LLM-based estimation. It evaluates explicit persisted counters and hard-evidence signals:

**Deterministic Inputs**:
- `attempt_count_total` (Integer): Total execution attempts across all agents for the job.
- `corrective_retry_count_for_current_executor` (Integer): Retries issued to the active executor.
- `reassignment_count` (Integer): Number of executor swaps performed.
- `same_outcome_streak` (Integer): Consecutive attempts producing the identical outcome.
- `same_blocker_fingerprint_streak` (Integer): Consecutive attempts producing the identical blocker fingerprint.
- `completed_openspec_task_delta` (Integer): `completed_tasks(t) - completed_tasks(t-1)`.
- `remaining_openspec_task_count` (Integer): Tasks remaining unchecked in `tasks.md`.
- `candidate_file_delta_count` (Integer): Net candidate files modified/created.
- `deterministic_checks_pass_delta` (Integer): `passed_checks(t) - passed_checks(t-1)`.
- `deterministic_checks_fail_delta` (Integer): `failed_checks(t) - failed_checks(t-1)`.
- `acceptance_evidence_delta` (Integer): Number of new verifiable acceptance artifacts produced.
- `blocker_resolution_delta` (Integer): Number of previously validated blockers resolved.
- `regression_detected` (Boolean): True if previously passing checks fail, completed tasks become incomplete, or valid files are corrupted/deleted.
- `policy_violation` (Boolean): True if executor violated worktree, secret, or git boundaries.
- `provider_available` (Boolean): True if primary provider capacity is available.
- `alternative_executor_eligible` (Boolean): True if alternate primary executor is configured and available.

**Progress Classification Rules**:
- `GOOD_PROGRESS`: `(completed_openspec_task_delta > 0 OR deterministic_checks_pass_delta > 0 OR acceptance_evidence_delta > 0)` AND `regression_detected = False` AND `policy_violation = False`.
- `PARTIAL_PROGRESS`: `candidate_file_delta_count > 0` AND `regression_detected = False` AND completion verification not yet satisfied.
- `NO_PROGRESS`: `completed_openspec_task_delta = 0` AND `deterministic_checks_pass_delta = 0` AND `candidate_file_delta_count = 0` AND `acceptance_evidence_delta = 0`.
- `REGRESSION`: `deterministic_checks_fail_delta > 0` OR previously completed tasks become incomplete OR candidate integrity check degrades.

### Decision 3: Configurable Hard Ceilings & Anti-Ping-Pong Bounds

The system enforces explicit configurable hard limits to eliminate infinite retry loops or endless oscillation between Codex and Antigravity:
- `max_corrective_retries_per_executor`: Default `2`.
- `max_reassignments_per_job`: Default `2`.
- `max_same_outcome_streak`: Default `2`.
- `max_same_false_blocker_streak`: Default `2`.

When any ceiling is exhausted and no safe automated continuation exists, the system deterministically transitions the job to `NEEDS_HUMAN`.

### Decision 4: Narrow Deterministic Blocker Validation & Fingerprinting

`BlockerValidationService` performs strictly deterministic validation without LLM architectural inference:
1. **Contract Check**: Is the claimed missing artifact or path explicitly mandated by OpenSpec or repo contracts?
2. **Known Integration Points**: Does the repository declare/expose the required capability through a registered module map (e.g. `src/minime/services/capacity_lifecycle_service.py` for capacity lifecycle)?
3. **Implementation Scope**: Is creating the missing file a normal implementation task within the active change?
4. **Invariant Check**: Is there a concrete failing credential or unavailable host dependency?

If equivalence cannot be determined deterministically, the service fails closed to `NEEDS_HUMAN`.

**Deterministic Blocker Fingerprint**:
Constructed as a SHA-256 hash or canonical string:
`fingerprint = sha256(f"{blocker_type}:{affected_requirement}:{failing_invariant}:{normalized_reason_code}")`

### Decision 5: Complete Continuation Decision Rule Table

| Rule | Outcome | Progress | Streak / Counters | Alternative Eligible? | Continuation Decision | Target Action |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **A** | `COMPLETED` | `GOOD_PROGRESS` | — | — | Advance | Build Candidate Manifest → Run Checks → Review |
| **B** | `PREMATURE_STOP` | `PARTIAL_PROGRESS` | `retries < max_retries` | — | `CORRECT_AND_RETRY` | Generate targeted prompt: list remaining OpenSpec tasks |
| **C** | `PREMATURE_STOP` | `NO_PROGRESS` | `retries >= max_retries` | Yes | `REASSIGN_AGENT` | Generate structured handoff → Swap to alternate executor |
| **D** | `FALSE_BLOCKER` | Any | `false_blocker_streak < max_streak` | — | `CORRECT_AND_RETRY` | Corrective prompt: identify known integration point |
| **E** | `FALSE_BLOCKER` | Any | `same_fingerprint_streak >= max_streak` | Yes | `REASSIGN_AGENT` | Generate structured handoff → Swap to alternate executor |
| **F** | `CHANGES_REQUIRED` | `GOOD_PROGRESS` | `retries < max_retries` | — | `CORRECT_AND_RETRY` | Corrective prompt: attach failing check evidence |
| **G** | `CHANGES_REQUIRED` | `REGRESSION` / `NO_PROGRESS` | `retries >= max_retries` | Yes | `REASSIGN_AGENT` | Generate structured handoff → Swap to alternate executor |
| **H** | `REAL_BLOCKER` (External) | — | — | — | `WAIT_EXTERNAL` / `NEEDS_HUMAN` | Transient external → `WAIT_EXTERNAL`; Unresolvable → `NEEDS_HUMAN` (No reassign) |
| **I** | `PROVIDER_EXHAUSTED` | — | — | — | `WAIT_EXTERNAL` | Invoke 005/006 capacity lifecycle (DRAIN fallback if eligible) |
| **J** | Any failure | — | `reassignment_count >= max_reassignments` | — | `NEEDS_HUMAN` | Escalation payload with full attempt history |
| **K** | `REASSIGN_AGENT` indicated | — | — | No | `NEEDS_HUMAN` | Escalation: alternate executor unavailable |
| **L** | Review Visibility Invalid | — | — | — | `WAIT_EXTERNAL` / `NEEDS_HUMAN` | Diagnostic `REVIEW_ENVIRONMENT_INVALID` recorded; retry/escalate |

### Decision 6: Restart Safety & Idempotency

To ensure daemon crashes during continuation transitions do not corrupt state or trigger duplicate reassignments:
- Each attempt is assigned a UUID `attempt_id`.
- Continuation decisions are persisted with a unique `decision_id` and committed in the same database transaction as the attempt completion.
- Handoff records are assigned an immutable `handoff_id`.
- On daemon recovery, `RestartRecoveryService` inspects active jobs: if an attempt concluded with `REASSIGN_AGENT` and a pending handoff exists, it resumes the exact pending handoff rather than generating a duplicate handoff or incrementing `reassignment_count` twice.

### Decision 7: Candidate Review Manifest & Visibility Proof

Prior to launching complementary review:
1. `CandidateManifestService` scans the worktree (`git status --porcelain` + filesystem walk) to capture all tracked modifications, staged files, untracked candidate files, and deletions.
2. The manifest records file paths, sizes, and SHA-256 hashes.
3. The reviewer execution harness verifies that the reviewer's execution sandbox has read access to all manifest entries.
4. If a reviewer reports a missing file finding for an artifact present in the manifest, the review verdict is rejected, and an evidence diagnostic of `REVIEW_ENVIRONMENT_INVALID` is recorded.

### Decision 8: Authorship Tracking & Review Independence

- Every attempt records the executor role (`codex`/`antigravity`) and model identity.
- If a candidate receives contributions from multiple executors across attempts, `is_mixed_authorship = True` is persisted.
- The complementary review report includes an explicit disclosure of mixed authorship.
- DeepSeek Direct independent audit remains mandatory and cannot be satisfied by an authoring model.
- Human merge remains final authority.

## Data Model & Alembic Migration Plan (007)

```
                       +-------------------+
                       |  execution_jobs   |
                       +---------+---------+
                                 | 1
                                 |
                                 | *
                       +---------v---------+
                       |   job_attempts    |
                       +----+----+----+----+
                            |    |    |
           +----------------+    |    +----------------+
           | 1                   | 1                   | 1
           | *                   | *                   | *
+----------v---------+ +---------v---------+ +---------v---------+
|   blocker_claims   | |   job_handoffs    | |candidate_manifests|
+--------------------+ +-------------------+ +-------------------+
```

### Table Schema Updates

1. **`job_attempts`**:
   - `id` (UUID, PK)
   - `job_id` (UUID, FK -> `execution_jobs.id`, indexed)
   - `attempt_number` (Integer, non-null)
   - `executor_role` (String, non-null)
   - `model_identity` (String, non-null)
   - `start_sha` (String, nullable)
   - `end_sha` (String, nullable)
   - `normalized_outcome` (Enum `ExecutionOutcome`, non-null)
   - `progress_classification` (Enum `ProgressClassification`, nullable)
   - `continuation_decision` (Enum `ContinuationDecision`, nullable)
   - `corrective_retries_count` (Integer, default 0)
   - `same_outcome_streak` (Integer, default 1)
   - `same_blocker_fingerprint_streak` (Integer, default 0)
   - `started_at` (DateTime TZ, non-null)
   - `completed_at` (DateTime TZ, nullable)
   - `duration_ms` (Integer, nullable)
   - `corrective_prompt` (Text, nullable)
   - `error_details` (JSONB, nullable)
   - `created_at` (DateTime TZ, non-null)

2. **`blocker_claims`**:
   - `id` (UUID, PK)
   - `job_id` (UUID, FK -> `execution_jobs.id`, indexed)
   - `attempt_id` (UUID, FK -> `job_attempts.id`, indexed)
   - `blocker_type` (String, non-null)
   - `blocker_fingerprint` (String, non-null, indexed)
   - `affected_requirement` (String, nullable)
   - `failing_invariant` (String, nullable)
   - `evidence` (JSONB, nullable)
   - `attempted_remediation` (Text, nullable)
   - `rationale` (Text, nullable)
   - `is_agent_solvable` (Boolean, default True)
   - `validation_verdict` (Enum `BlockerValidationVerdict`, non-null)
   - `validation_rationale` (Text, nullable)
   - `available_integration_points` (JSONB, nullable)
   - `created_at` (DateTime TZ, non-null)

3. **`job_handoffs`**:
   - `id` (UUID, PK)
   - `job_id` (UUID, FK -> `execution_jobs.id`, indexed)
   - `from_attempt_id` (UUID, FK -> `job_attempts.id`)
   - `to_attempt_id` (UUID, FK -> `job_attempts.id`, nullable)
   - `from_executor` (String, non-null)
   - `to_executor` (String, non-null)
   - `worktree_path` (String, non-null)
   - `base_sha` (String, non-null)
   - `candidate_sha` (String, non-null)
   - `completed_tasks` (JSONB, non-null)
   - `remaining_tasks` (JSONB, non-null)
   - `manifest_summary` (JSONB, non-null)
   - `checks_summary` (JSONB, non-null)
   - `blockers_summary` (JSONB, nullable)
   - `architectural_notes` (JSONB, nullable)
   - `do_not_redo_guidance` (JSONB, nullable)
   - `authorship_history` (JSONB, non-null)
   - `is_consumed` (Boolean, default False)
   - `created_at` (DateTime TZ, non-null)

4. **`candidate_manifests`**:
   - `id` (UUID, PK)
   - `job_id` (UUID, FK -> `execution_jobs.id`, indexed)
   - `attempt_id` (UUID, FK -> `job_attempts.id`, nullable)
   - `candidate_sha` (String, non-null)
   - `tracked_files` (JSONB, non-null)
   - `staged_files` (JSONB, non-null)
   - `untracked_files` (JSONB, non-null)
   - `deleted_files` (JSONB, non-null)
   - `total_files_count` (Integer, non-null)
   - `manifest_hash` (String, non-null)
   - `created_at` (DateTime TZ, non-null)

5. **`evidence_diagnostics`**:
   - `id` (UUID, PK)
   - `job_id` (UUID, FK -> `execution_jobs.id`, indexed)
   - `attempt_id` (UUID, FK -> `job_attempts.id`, nullable)
   - `stage_type` (String, non-null)
   - `check_name` (String, nullable)
   - `diagnostic_status` (Enum `EvidenceDiagnosticStatus`: `PASS`, `FAIL`, `SKIPPED_BY_POLICY`, `ENVIRONMENT_UNAVAILABLE`, `EVIDENCE_NOT_REPRODUCIBLE`, `REVIEW_ENVIRONMENT_INVALID`)
   - `environment_identity` (String, non-null)
   - `candidate_sha` (String, non-null)
   - `reason` (Text, nullable)
   - `evidence_reference` (JSONB, nullable)
   - `created_at` (DateTime TZ, non-null)

6. **`execution_jobs` column additions**:
   - `attempt_count` (Integer, default 1)
   - `reassignment_count` (Integer, default 0)
   - `current_executor` (String, nullable)
   - `latest_outcome` (String, nullable)
   - `latest_progress` (String, nullable)
   - `continuation_decision` (String, nullable)
   - `is_mixed_authorship` (Boolean, default False)
   - `escalation_reason` (Text, nullable)
   - Add enum value `NEEDS_HUMAN` to `JobStatus`.

## Risks / Trade-offs

- **[Risk] Repetitive false blockers exhausting retries** → *Mitigation*: Deterministic blocker fingerprinting detects identical claims and triggers reassignment on streak = 2, preventing wasted retries.
- **[Risk] Endless executor ping-pong (Codex ↔ Antigravity)** → *Mitigation*: Hard ceiling `max_reassignments_per_job = 2`. When reached, the system transitions immediately to `NEEDS_HUMAN`.
- **[Risk] Reviewer subagent failing due to sandbox/environment restrictions** → *Mitigation*: Diagnostic `REVIEW_ENVIRONMENT_INVALID` separates environmental inability from candidate code defects, preventing false rejection of valid candidates.
- **[Risk] Daemon crash during reassignment leaving partial state** → *Mitigation*: Atomic database transactions, stable `attempt_id` / `handoff_id` identities, and restart recovery resume pending handoffs idempotently.
