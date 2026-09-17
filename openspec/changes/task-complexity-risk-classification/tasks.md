## 1. Domain Enums and Models

- [x] 1.1 Add `TaskComplexity` enum (LOW, MEDIUM, HIGH, UNKNOWN) to `src/minime/domain/enums.py`
- [x] 1.2 Add `TaskSurfaceKind` enum (DOCS_ONLY, TESTS_ONLY, CONFIG_ONLY, MIGRATION_SCHEMA, BACKEND_SERVICE, UI_FRONTEND, INFRASTRUCTURE_DEPLOYMENT, PROVIDER_INTEGRATION, ORCHESTRATION_LIFECYCLE, SECURITY_AUTH, MIXED, UNKNOWN) to `src/minime/domain/enums.py`
- [x] 1.3 Add `ClassificationStage` enum (PRE_EXECUTION, POST_MATERIALIZATION) and `ClassificationCompleteness` enum (COMPLETE, PARTIAL, MINIMAL) to `src/minime/domain/enums.py`
- [x] 1.4 Add `TaskRiskDimension` enum (CODE_CHANGE_BREADTH, ARCHITECTURAL_IMPACT, PERSISTENCE_IMPACT, SECURITY_AUTH_IMPACT, PRODUCTION_RUNTIME, PROVIDER_ORCHESTRATION, DESTRUCTIVE_OPERATIONS, DEPLOYMENT_CONFIG) to `src/minime/domain/enums.py`
- [x] 1.5 Add `TaskRiskProfile`, `TaskClassificationSnapshot`, and `TaskClassificationProfile` Pydantic domain models to `src/minime/domain/models.py`

## 2. Centralized Classification Rules

- [x] 2.1 Create `src/minime/services/classification_rules.py` with `CLASSIFIER_VERSION = "1.0.0"` and centralized path/surface rule constants (`PATH_RISK_SURFACES`, `PATH_SURFACE_MAPPINGS`, `SECURITY_PATH_MARKERS`, `PROVIDER_ORCHESTRATION_PATH_MARKERS`, `DEPLOYMENT_PATH_MARKERS`, `CONFIG_FILE_PATTERNS`, `DESTRUCTIVE_MIGRATION_PATTERNS`, `WEAK_SURFACE_HINTS`)
- [x] 2.2 Define destructive operation patterns that require actual SQL DDL evidence (DROP TABLE, DROP COLUMN, TRUNCATE, sa.Column.drop) — not filename or natural-language matching

## 3. Task Complexity Risk Classifier Service

- [x] 3.1 Create `src/minime/services/task_complexity_risk_classifier.py` with `TaskComplexityRiskClassifier` class and `classify_pre_execution(change, tasks, proposal_text)` entry point
- [x] 3.2 Implement `classify_post_materialization(pre_execution_snapshot, diff_file_paths, migration_files, design_content)` entry point
- [x] 3.3 Implement `_extract_signals(diff_paths, ...)` shared signal extraction using centralized rules from `classification_rules.py`
- [x] 3.4 Implement deterministic `_extract_complexity(signals)`, `_extract_risk_profile(signals)`, `_extract_surface_kind(signals)` functions with evidence precedence (Tier 1 observed > Tier 2 canonical rules > Tier 3 weak hints)
- [x] 3.5 Implement fail-closed behavior: return UNKNOWN with `classification_completeness=MINIMAL` and enumerated missing signals when evidence is insufficient

## 4. Persistence — DB Model and Migration

- [x] 4.1 Add `TaskClassificationSnapshotModel` to `src/minime/db/models.py` with table `task_classification_snapshots` (PK: `String(64)`, FKs: `String(64)` to `changes.id` and `jobs.id` with `ondelete=SET NULL`, self-FK `pre_execution_snapshot_id`, timestamps: `DateTime(timezone=True)`, JSON columns with `server_default`, Boolean with `server_default=sa.false`)
- [x] 4.2 Add optional `classification_snapshot_id` column to `JobModel` and `latest_classification_snapshot_id` to `ChangeModel` (both nullable FK to `task_classification_snapshots.id`)
- [x] 4.3 Create Alembic migration `022_task_classification_snapshots` (new table + FK columns + indexes, forward and reverse) **Note: numbered 021 on current base; provisional pending post-stabilization rebase.**

## 5. Repository Layer

- [x] 5.1 Add `TaskClassificationSnapshotRepositoryInterface` to `src/minime/domain/interfaces.py`
- [x] 5.2 Implement repository methods in `src/minime/db/repository.py` (create snapshot, find by change, find by job, find latest)

## 6. Lifecycle Integration

- [x] 6.1 Trigger pre-execution classification when a change reaches `READY` or job is admitted, persisting snapshot and updating `changes.latest_classification_snapshot_id`
- [x] 6.2 Trigger post-materialization classification after implementation produces a candidate diff (in `outcome_governance.py` or `execution_pipeline.py`), linking to pre-execution snapshot and updating `jobs.classification_snapshot_id`
- [x] 6.3 Ensure classification failure during lifecycle is observable (error event/log) without blocking the lifecycle stage

## 7. Non-Interference Verification

- [x] 7.1 Verify that `ProviderPolicyService.evaluate_selection()` produces identical results before and after classification snapshots exist
- [x] 7.2 Verify that `ContinuationEngine.decide()` and scheduler admission produce identical results before and after classification snapshots exist
- [x] 7.3 Verify that the classifier makes zero external provider API calls (zero inference token consumption)

## 8. Acceptance Tests

- [x] 8.1 Implement deterministic classification scenario tests covering all 32 acceptance scenarios from the spec (docs-only, tests-only, isolated service, cross-module, migration, auth, scheduler, provider, deployment, destructive, unknown, determinism, version stability, pre/post execution, mismatch, legacy, multi-capability, cross-cutting, UI-only, non-interference)
- [x] 8.2 Implement failure-injection tests (missing inputs produces UNKNOWN, persistence failure is observable, legacy items marked as legacy)