## Context

mini me already has comprehensive lifecycle infrastructure: `ChangeStatus` (DISCOVERED → READY → IN_PROGRESS → BLOCKED → DONE → CANCELLED) in PostgreSQL, `OrchestrationStage` (15 stages from ADMITTED to COMPLETED), `JobStatus` (18 states), `PostMergeReconciliationService` that drives sync/archive, `OpenSpecSyncService` that performs filesystem sync/archive, and `OpenSpecAdapter` that discovers and evaluates changes.

**Existing deterministic enforcement** (not agent-instruction-only):
- Review candidate binding: `_validate_review_authority()` (line 2451) checks candidate_sha, base_sha, manifest_id/hash, generation, reviewer identity (Rule G independence), and structured verdict. This gate already fails closed on mismatched or missing review evidence.
- Artifact presence: `ReadinessService.evaluate_change_readiness()` checks proposal.md, tasks.md, design.md, specs/ existence via `OpenSpecAdapter.evaluate_artifacts()`.
- Task checkbox state: `OpenSpecAdapter.evaluate_artifacts()` parses `tasks.md` checkboxes to evaluate completion.

**Verified enforcement gaps** (the target of this change):
- No strict-validity gate (`openspec validate --strict` not invoked during readiness or admission).
- No pre-admission implementation attribution (commits predating orchestration run are not detected).
- No VERIFY gate at `READY_FOR_HUMAN_MERGE` transition (OpenSpec coherence, task implementation evidence, scope integrity).
- No SYNC verification blocking terminal state after merge (sync failure is logged as warning, terminal state advances regardless).
- No ARCHIVE verification blocking terminal state after merge (archive failure is logged as warning, terminal state advances regardless).
- No task-evidence backing (tasks checked complete without corresponding candidate diff are not detected).
- No integrity auditor (no structured cross-cutting audit of all dimensions).

**Archive authority**: `OpenSpecSyncService.archive_change()` (line 110) writes to `openspec/changes/archive/`. The `opsx-archive` workflow creates `archive` under `planningHome.changesDir`. The existing service also checks `openspec/archive/` as a fallback (line 128) when the active directory is already gone. `openspec/changes/archive/` is the canonical archive location; the single entry in `openspec/archive/` (`014-tui-operator-console`) is classified as `ARCHIVE_LAYOUT_AMBIGUITY` — possibly manual or from a different workflow version — not as invalid or debt.

The design constraint: DO NOT create a parallel lifecycle state machine. Compose with existing truths.

## Goals / Non-Goals

**Goals:**
- Add deterministic lifecycle gates that fail closed on existing PostgreSQL/OpenSpec/Git evidence
- Create an integrity auditor that reports on repository OpenSpec health
- Define CLOSED semantics composing OpenSpec lifecycle + project delivery evidence
- Classify legacy changes without fabricating history
- Strengthen existing capabilities at their natural enforcement points

**Non-Goals:**
- New global lifecycle state machine or monolithic lifecycle enum
- Autonomous cleanup or auto-repair of integrity violations
- Moving or re-archiving historical changes
- Fabricating missing OpenSpec history
- CLI-first design (the `openspec-lifecycle-governance` spec is the contract; CLI is optional integration)

## Decisions

### D1 - Gate composition over monolithic state machine

**Choice**: Define lifecycle gates as standalone, composable predicates that read from existing PostgreSQL tables, OpenSpec filesystem state, and orchestration records. Each gate returns `{PASS, FAIL, UNKNOWN}` with a structured reason.

**Rationale**: The existing enums (`ChangeStatus`, `OrchestrationStage`, `JobStatus`, `OrchestrationStopOutcome`) already express lifecycle state. A new lifecycle enum would duplicate these, creating synchronization risk. Gates compose to answer specific questions ("is this change strict-valid?", "has this change been synced?") using the authoritative source for each fact.

**Alternatives considered**: A centralized lifecycle state machine with transitions and guard conditions. Rejected because it would duplicate existing enums, require migration of all existing state, and create a two-source-of-truth problem.

### D2 - Integrity auditor as a PostgreSQL-backed service

**Choice**: `OpenSpecIntegrityService` that performs a point-in-time audit of the repository's OpenSpec state, persisting findings in a new `integrity_findings` table linked to the project. The audit evaluates: active change validity, merged-but-unsynced changes, closed-but-unarchived changes, orphan directories, and task-state contradictions.

**Rationale**: Audit findings must survive process restart. A dedicated table keeps findings queryable and allows operators to track reconciliation over time. The audit is read-only: it never mutates filesystem state or OpenSpec artifacts.

**Schema**: `integrity_findings(id, project_id, executed_at, overall_status, findings JSON, evidence_gaps JSON)`. The `findings` column stores a list of `{severity, category, change_name, description, evidence}` objects. `overall_status` is `PASS | FAIL | UNKNOWN`.

### D3 - Gate enforcement points in existing services

**Choice**: Hook lifecycle gates at their natural enforcement points in existing services:

| Gate | Enforcement Point | Service |
|------|-------------------|---------|
| Strict-validity | Readiness evaluation | `ReadinessService` via `OpenSpecAdapter.evaluate_artifacts()` |
| APPLY attribution | Orchestration admission | `OrchestrationService` / autonomous scheduler admission |
| VERIFY | Pre-READY_FOR_HUMAN_MERGE | Orchestration pipeline stage transition |
| Review candidate binding | Pre-READY_FOR_HUMAN_MERGE | Orchestration pipeline stage transition |
| SYNC verification | Post-merge reconciliation | `PostMergeReconciliationService` |
| ARCHIVE verification | Post-merge reconciliation | `PostMergeReconciliationService` |

**Rationale**: These enforcement points already exist in the pipeline. Adding gates there requires no new service entry points and preserves the existing control flow. Each gate is independently evaluable; a gate failure at one point does not cascade to others.

### D4 - Sync and archive verification

**Choice**: After `OpenSpecSyncService.sync_change_specs()` completes, verify by reading the target canonical spec and confirming the synchronized requirements are present. After `OpenSpecSyncService.archive_change()` completes, verify the change directory is gone and the archive artifact exists. Record verification results as immutable events in the `events` table before advancing the orchestration stage.

**Rationale**: The existing services perform the actual sync/archive (filesystem operations). Verification is a read-only check afterward, not a replacement. This preserves the existing sync/archive implementation while adding the enforcement layer.

**Target archive location**: `openspec/changes/archive/` — the location the existing `OpenSpecSyncService.archive_change()` writes to, the `opsx-archive` workflow targets, and the installed canonical mechanism uses. The separate `openspec/archive/` directory contains a single entry (`014-tui-operator-console`) classified as `ARCHIVE_LAYOUT_AMBIGUITY` — the integrity auditor detects the split and reports it without declaring either location invalid.

### D5 - Classification and DB/OpenSpec authority

**Choice**: A `classify_change()` method in `OpenSpecIntegrityService` that categorizes each active change or archive entry into: `CANONICAL` (has current-schema artifacts, strict-valid), `LEGACY_STRUCTURAL` (artifacts present but schema predates current), `LEGACY_INCOMPLETE` (missing required artifacts), `LEGACY_ARCHIVE_DEBT` (archive entry without OpenSpec evidence), `ORPHAN` (directory without discoverable artifacts and no pipeline record), `ARCHIVE_LAYOUT_AMBIGUITY` (entry in a non-canonical archive location).

**DB/OpenSpec authority**: An OpenSpec change directory can legitimately exist without a PostgreSQL record in the `changes` table. The `ReadinessService` creates DB records at first evaluation (line 355), but directories are discovered first by `OpenSpecAdapter.discover_changes()` before any DB record exists. A directory lacking a DB record is only ORPHAN when it also lacks discoverable OpenSpec artifacts (no `.openspec.yaml` AND no `proposal.md` AND no `specs/`) AND no orchestration run references it AND it is not under the archive path.

**Missing `.openspec.yaml`**: The `.openspec.yaml` metadata file was introduced with the spec-driven schema. Changes predating this schema may legitimately lack it while still having complete artifacts interpretable by current tooling. Classification evaluates artifact completeness against the schema the change's content appears to target, not solely against file-presence rules. A change with `proposal.md`, `tasks.md`, `design.md`, and `specs/` that passes `openspec validate` is CANONICAL regardless of `.openspec.yaml` presence.

**Rationale**: Classification is a point-in-time evaluation, not a persistent change status. DB records are created on demand, not at directory creation. Classifications may evolve as governance matures; keeping them in audit findings avoids polluting the operational state model.

### D6 - Configurable gate policy

**Choice**: New project-level configuration fields (`strict_validation_required`, `verify_gate_required`, `sync_gate_required`, `archive_gate_required`) defaulting to `true`. This allows gradual adoption for existing projects while defaulting to strict enforcement.

**Rationale**: The project registry (`projects` table) is the canonical configuration store. Adding gate policy there follows existing patterns (e.g., `checks`, `implementer`, `reviewer`).

### D7 - CLOSED semantics

**Choice**: `CLOSED` is not a new `ChangeStatus` value. It is a computed evaluation point that composes: (1) OpenSpec lifecycle completion = verify + sync + archive all evidenced; (2) project delivery completion = merge + deploy + production proving. The integrity auditor reports whether a change satisfies CLOSED, but the `changes.status` field remains `DONE` (the existing terminal status) until the DONE→CLOSED mapping is fully proven.

**Rationale**: `ChangeStatus.DONE` already exists as the terminal state. Adding `CLOSED` prematurely without deployment/proving integration would create an inconsistency. The integrity auditor evaluates CLOSED as a separate concern, and the status field stays as-is until deployment/proving integration is complete.

### D8 - New domain additions

**New `EventType` values** (added): `POST_MERGE_SYNC_VERIFIED`, `POST_MERGE_ARCHIVE_VERIFIED` (sync/archive verification evidence), `PRODUCTION_DEPLOYED`, `PRODUCTION_VERIFIED` (CLOSED delivery evidence).

**New `IntegrityFindingCategory` values** (stored in JSON, not a DB enum): `INVALID_ACTIVE_CHANGE`, `MERGED_BUT_UNSYNCED`, `CLOSED_BUT_UNARCHIVED`, `ORPHAN_DIRECTORY`, `TASK_STATE_CONTRADICTION`, `LEGACY_CLASSIFICATION`.

**Deferred (intentionally NOT emitted in this change)**: `LIFECYCLE_GATE_EVALUATED`, `LIFECYCLE_GATE_BLOCKED`, `INTEGRITY_AUDIT_COMPLETED`, `LEGACY_CLASSIFIED`, and `FABRICATED_HISTORY_DETECTED` events, plus the `SPEC_DRIFT` and `MISSING_ARTIFACT` finding categories. This change persists integrity results to the `integrity_findings` table and returns structured `GateResult`s as its declared evidence mechanism; missing-artifact active changes are classified `LEGACY_INCOMPLETE`.

**No new DB enums**: All new finding categories are string values in JSON columns; no migration of existing enum types is required.

## Risks / Trade-offs

- **Performance**: Integrity audit scans all active changes, archive directories, and orchestration records. For repositories with hundreds of archived changes, this could be slow. Mitigation: the audit is on-demand (not per-scheduler-tick), and results are cached in `integrity_findings` until the next explicit audit.

- **Strict validation dependency on openspec CLI**: The strict-validity gate calls `openspec validate --strict --type change` as a subprocess. If the CLI is unavailable or version-incompatible, strict validation cannot run. Mitigation: `OpenSpecAdapter` already shells out to the CLI; gate evaluation handles subprocess failures as UNKNOWN (blocking, not PASS).

- **Migration risk**: Adding `integrity_findings` table and gate policy columns is forward-compatible (new table, nullable columns). No existing data is modified. Rollback is a migration down-revision.

## Open Questions

- **Exact `openspec validate` exit code / output parsing**: The strict-validity gate must parse `openspec validate --strict --type change` output. The CLI's JSON output format for validation results should be confirmed during implementation before finalizing the parser.
- **Review evidence SHA binding**: The `reviews` table already has `candidate_sha` and `base_sha` columns. Confirm these are populated for all review paths (including drain/recovery) before relying on them for the gate.