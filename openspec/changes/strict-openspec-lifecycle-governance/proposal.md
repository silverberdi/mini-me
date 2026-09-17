# Proposal: Strict OpenSpec Lifecycle Governance

## Why

OpenSpec lifecycle integrity is partially enforced. Existing deterministic mechanisms include: review authority validation with candidate-SHA/manifest/generation binding (`_validate_review_authority`), artifact presence checks during readiness evaluation (`ReadinessService`), and structured reviewer independence (Rule G). However, critical gaps remain: no strict-validity gate, no pre-admission implementation attribution, no sync/archive verification blocking terminal state, no task-evidence backing, and no integrity auditor. The repository contains lifecycle integrity gaps — stale changes, missing metadata, task state decoupled from real execution — because these specific gates are absent. A competent architect cloning the repository cannot distinguish canonical truth from drift, history from accident, or completed work from abandoned scaffolding. This must be fixed now because mini me's autonomous delivery loop depends on OpenSpec as a lifecycle contract, and every additional change written without governance deepens the accumulated debt.

## What Changes

- **Strict-validity gate**: No change enters READY without passing `openspec validate --strict --type change`. Invalid OpenSpec state blocks admission.

- **APPLY attribution gate**: Implementation tracked in orchestration runs SHALL be provably attributable to an admitted OpenSpec change. Retrospective spec fabrication is detected and blocked.

- **VERIFY gate**: The orchestration human-gate contract SHALL require verification evidence (OpenSpec validate, implementation/task coherence, scope integrity) before `READY_FOR_HUMAN_MERGE`.

- **Independent review candidate binding**: The existing `_validate_review_authority` gate already enforces candidate-SHA/manifest/generation binding. The integrity auditor SHALL detect and report stale or mismatched review evidence.

- **Post-merge SYNC enforcement**: The existing `autonomous-post-merge-closure` sync phase SHALL verify sync completed before declaring terminal state. Merged-but-unsynced changes are detectable.

- **ARCHIVE enforcement**: The existing archive phase SHALL verify the change directory was removed from active changes and the archive artifact is intact. Closed-but-unarchived changes are detectable.

- **OpenSpec integrity auditor**: A service-backed audit capability that evaluates the repository's OpenSpec state: active change validity, merged-but-unsynced changes, closed-but-unarchived changes, artifact completeness, task-state contradictions, and orphan directories.

- **CLOSED semantics**: Define strong CLOSED semantics integrating OpenSpec lifecycle completion (verify + sync + archive) with project delivery completion (merge + deploy + production proving) without conflating them into one lifecycle enum.

- **Legacy classification**: Truthful classification of historical changes lacking canonical OpenSpec evidence as legacy/non-canonical debt. No retrospective fabrication.

- **Truthful failure**: All lifecycle gates SHALL fail closed with exact missing/broken condition reported. No silent repair, no invented history, no assumed progress.

## Capabilities

### New Capabilities

- `openspec-lifecycle-governance`: Lifecycle gate framework, integrity auditor, CLOSED semantics, truthful failure contract, legacy/non-canonical classification.

### Modified Capabilities

- `openspec-readiness`: Strengthen "Structured readiness evaluation" with strict OpenSpec validation requirement.
- `autonomous-change-orchestration`: Strengthen "Single-change admission" with APPLY attribution verification; strengthen "Human-gate contract" with VERIFY gate requirement.
- `autonomous-post-merge-closure`: Strengthen "Native OpenSpec Sync and Archive" with post-sync/archive verification gates; strengthen "Terminal State Reconciliation" with CLOSED semantics requiring sync+archive evidence.
- `complementary-reviewer-policy`: Strengthen "Strict complementary role pairing" with candidate-SHA-bound review evidence requirement.
- `openspec-task-tracking`: Strengthen "Task completion verification" with integrity checks against mass-checking and evidence-less completion.

## Impact

- **Domain**: New `ChangeStatus` values (`CLOSED`), new `EventType` values for lifecycle gate events, new `integrity_findings` table for audit results.
- **Persistence**: Versioned Alembic migration adding `integrity_findings` table, extending `changes` with `lifecycle_gate_status` column, extending `events` with new event types.
- **Services**: New `OpenSpecIntegrityService` for audit; modifications to `ReadinessService`, `OrchestrationService`, `PostMergeReconciliationService`, `OpenSpecAdapter`.
- **API/CLI**: Audit endpoint at `/api/v1/openspec/integrity`; optional CLI subcommand under existing `orchestrate` group. No new top-level CLI surface.
- **Config**: Lifecycle gate policy configuration (`strict_validation_required`, `verify_gate_required`, `sync_gate_required`, `archive_gate_required`) with safe defaults.
- **Scheduler**: Readiness evaluation gates are invoked during admission; no changes to tick cadence or provider routing.
- **No UI change**: No human validation scenarios required.
- **Historical changes**: Read-only classification only; zero mutations to existing change archives, specs, or artifact files.