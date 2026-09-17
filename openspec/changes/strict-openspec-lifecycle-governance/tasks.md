# Tasks: Strict OpenSpec Lifecycle Governance

Instructions: Treat specs as behavioral authority. `openspec-lifecycle-governance` is the primary capability; `openspec-readiness`, `autonomous-change-orchestration`, `autonomous-post-merge-closure`, `complementary-reviewer-policy`, and `openspec-task-tracking` deltas define the integration contracts. Scope is limited to this change only. Do NOT implement provider-execution-safety-stabilization, legacy archive relocation, historical artifact fabrication, or autonomous merge.

## 1. Foundation and Strict-Validity Gate

- [x] 1.1 Add `.openspec.yaml` metadata to the change scaffold and configure gate-policy fields (`strict_validation_required`, `verify_gate_required`, `sync_gate_required`, `archive_gate_required`) on the `Project` domain model and Alembic migration with safe defaults (`true`).
- [x] 1.2 Implement `LifecycleGate.evaluate()` base class with `{PASS, FAIL, UNKNOWN}` result contract and structured reason output.
- [x] 1.3 Implement `StrictValidationGate` that shells out to `openspec validate --strict --type change` via `OpenSpecAdapter`, parses the result, and returns PASS/FAIL/UNKNOWN with the validation error details.
- [x] 1.4 Integrate strict-validity gate into `ReadinessService` evaluation: call the gate during readiness check, add `OPENSPEC_STRICT_VALIDATION_FAILED` as a structured unmet reason when the gate returns FAIL.
- [x] 1.5 Write deterministic tests: missing planning artifact fails the existing artifact-completeness readiness gate (blocked) even when canonical strict validation passes; malformed spec with required artifacts fails canonical strict validation; valid complete change passes both gates; openspec CLI unavailable returns UNKNOWN (blocked).
- Completion signal: readiness evaluation blocks changes that fail strict validation; valid changes proceed.

## 2. APPLY Attribution Gate

- [x] 2.1 Implement `ApplyAttributionGate` that verifies: (a) an OpenSpec change exists for the admission target, (b) the change has valid artifacts, (c) no implementation commits in the candidate worktree predate the orchestration run creation timestamp.
- [x] 2.2 Integrate the gate into autonomous orchestration admission: when admission is requested (via scheduler or explicit orchestrate start), gate evaluates before `OrchestrationRun` creation.
- [x] 2.3 Implement lifecycle drift detection: if implementation artifacts (commits, modified files under a change's worktree) exist before an orchestration run admits the change, gate returns FAIL with a LIFECYCLE_DRIFT reason.
- [x] 2.4 Write deterministic tests: admission attempted with no OpenSpec change (blocked), admission attempted with predating implementation commits (lifecycle drift, blocked), valid admission with clean worktree (allowed), duplicate admission attempt (refused with existing run identity).
- Completion signal: no orchestration run created without attributable OpenSpec change; drift detected and blocked.

## 3. VERIFY and Independent Review Gates

- [x] 3.1 Implement `VerifyGate` that requires: (a) `openspec validate --strict --type change` passes for the change, (b) implementation/task coherence (completed tasks have corresponding candidate diff evidence), (c) scope integrity (no unapproved changes outside the change's spec scope).
- [x] 3.2 Implement `ReviewEvidenceReport` in the integrity auditor that verifies: (a) a `reviews` record exists with `status = REVIEW_COMPLETED` for the candidate, (b) the existing `_validate_review_authority` gate would pass with current candidate state, (c) the review's bound candidate SHA has not been superseded by remediation. Report STALE_REVIEW if evidence is mismatched.
- [x] 3.3 Integrate the VERIFY gate into the orchestration pipeline's `PR_PREPARED` → `READY_FOR_HUMAN_MERGE` transition: gate evaluates before the human-gate outcome is set. Review candidate binding is already enforced by `_validate_review_authority`; the VERIFY gate adds OpenSpec coherence and task-evidence checks.
- [x] 3.4 Write deterministic tests: verify fails when openspec validate fails (blocked), verify fails when tasks checked but diff empty (blocked), integrity audit detects stale review evidence (STALE_REVIEW finding), both gates pass for valid candidate (allowed).
- Completion signal: orchestration pipeline blocks READY_FOR_HUMAN_MERGE when verify or review evidence is missing, stale, or mismatched.

## 4. Post-Merge SYNC and ARCHIVE Enforcement

- [x] 4.1 Add sync verification to `PostMergeReconciliationService`: after `OpenSpecSyncService.sync_change_specs()` completes, read the target canonical spec(s) and confirm synchronized requirements are present, record a `POST_MERGE_SYNC_VERIFIED` event.
- [x] 4.2 Add archive verification to `PostMergeReconciliationService`: after `OpenSpecSyncService.archive_change()` completes, confirm the change directory is removed from `openspec/changes/` and the archive artifact exists at `openspec/changes/archive/{date}-{name}/`, record a `POST_MERGE_ARCHIVE_VERIFIED` event.
- [x] 4.3 Gate terminal state transition (`COMPLETED`) on sync and archive verification events. If either verification event is missing, stop with `WAITING_EXTERNAL` and do not transition to `COMPLETED`.
- [x] 4.4 Write deterministic tests: sync completes but archive fails (terminal state blocked), archive completes but sync evidence missing (terminal state blocks), both verified (COMPLETED allowed), archive target collision (archive fails, change remains active).
- Completion signal: post-merge service blocks COMPLETED when sync or archive evidence is unverified; verification failures are recoverable.

## 5. OpenSpec Integrity Auditor

- [x] 5.1 Add Alembic migration creating `integrity_findings` table: `id` (PK), `project_id` (FK), `executed_at` (timestamptz), `overall_status` (String: PASS/FAIL/UNKNOWN), `findings` (JSON array of finding objects), `evidence_gaps` (JSON array of gap descriptions).
- [x] 5.2 Implement `OpenSpecIntegrityService` with `run_audit(project_id)` method orchestrating all check phases and persisting results to `integrity_findings`.
- [x] 5.3 Implement active-change validation check: for each change under `openspec/changes/` with a database record, run `openspec validate --strict --type change`, report INVALID_ACTIVE_CHANGE for any failure.
- [x] 5.4 Implement merged-but-unsynced detection: for each orchestration run in COMPLETED or PR_PREPARED with a merged PR, check whether canonical specs contain the synchronized requirements; report MERGED_BUT_UNSYNCED where evidence is missing.
- [x] 5.5 Implement closed-but-unarchived detection: for each run in COMPLETED where the change directory still exists under `openspec/changes/`, report CLOSED_BUT_UNARCHIVED.
- [x] 5.6 Implement orphan directory detection: scan `openspec/changes/` (excluding `archive/`) for directories without discoverable OpenSpec artifacts (no `.openspec.yaml`, no `proposal.md`, no `specs/`), no `changes` database record, and no active orchestration run referencing them. Directories with artifacts but no DB record are noted as observations, not classified as orphans.
- [x] 5.7 Implement task-state contradiction detection: compare `tasks.md` checkbox states against orchestration stage evidence and candidate diff; report TASK_STATE_CONTRADICTION where tasks are marked complete but candidate diff contains zero corresponding modifications or no IMPLEMENTING stage events exist.
- [x] 5.8 Implement legacy classification: for each change or archive entry, classify into CANONICAL, LEGACY_STRUCTURAL, LEGACY_INCOMPLETE, LEGACY_ARCHIVE_DEBT, ORPHAN, or ARCHIVE_LAYOUT_AMBIGUITY based on artifact completeness, schema compatibility, and archive location. Classification MUST NOT fabricate missing artifacts. Missing `.openspec.yaml` alone SHALL NOT cause invalidity if other artifacts are complete and valid.
- [x] 5.9 Add API endpoint `GET /api/v1/openspec/integrity?project_id=<id>` returning the most recent audit result, and `POST /api/v1/openspec/integrity/audit` triggering a fresh audit.
- [x] 5.10 Write deterministic tests: healthy repository (PASS), invalid active change (FAIL), merged-but-unsynced (FAIL with specific finding), closed-but-unarchived (FAIL with specific finding), orphan directory (WARNING finding), insufficient evidence for dimension (UNKNOWN), legacy classification does not fabricate history.
- Completion signal: integrity audit returns structured PASS/FAIL/UNKNOWN with specific findings for each detected condition.

## 6. Integration, Strict Validation, and Closure

- [x] 6.1 Write end-to-end integration test exercising the complete lifecycle gate chain: strict-validity → APPLY attribution → VERIFY → sync verification → archive verification → integrity audit PASS. Existing review candidate binding is already enforced by `_validate_review_authority`; confirm it remains functional in the gate chain.
- [x] 6.2 Write CLOSED semantics test: change with OpenSpec lifecycle complete but deployment not proven (CLOSED not satisfied), change with both lifecycle and delivery complete (CLOSED satisfied).
- [x] 6.3 Run `openspec validate --strict --type change` on this change and confirm PASS.
- [x] 6.4 Run full focused test suite (`pytest tests/ -k "lifecycle or integrity or strict_validation or apply_gate or verify_gate or sync_gate or archive_gate or review_binding or legacy"`) and confirm all pass; run `ruff check` and confirm clean.
- Completion signal: strict validation PASS, focused test suite green, ruff clean, no implementation code outside this change modified.
