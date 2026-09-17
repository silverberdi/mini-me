# task-complexity-risk-classification Specification

## Purpose

Deterministic, explainable, versioned classification of work complexity, multidimensional risk, and structural surface from observable evidence, producing stable snapshots for downstream routing and telemetry consumers.

## Requirements

### Requirement: Deterministic Task Complexity Classification
The system SHALL deterministically classify the complexity of a change or task into one of: `LOW`, `MEDIUM`, `HIGH`, or `UNKNOWN`. Classification SHALL be based solely on observable structural evidence (file count, module spread, migration presence, capability breadth) and SHALL NOT use LLM inference, random behavior, or provider-dependent signals.

#### Scenario: Docs-only change receives LOW complexity
- **WHEN** a change modifies only files under `docs/` or only `.md` files, affects a single top-level directory, and modifies 3 or fewer files
- **THEN** complexity SHALL be `LOW`

#### Scenario: Single isolated service change receives MEDIUM complexity
- **WHEN** a change modifies 4 to 15 files within a single service module and does not include a migration file
- **THEN** complexity SHALL be `MEDIUM`

#### Scenario: Cross-module change with migration receives HIGH complexity
- **WHEN** a change modifies files across more than 3 top-level directories OR includes a new Alembic migration file OR modifies more than 15 files
- **THEN** complexity SHALL be `HIGH`

#### Scenario: Incomplete evidence produces UNKNOWN complexity
- **WHEN** no structural evidence is available and no pre-execution metadata exists
- **THEN** complexity SHALL be `UNKNOWN` with missing signal reasons recorded

### Requirement: Multi-Dimensional Risk Profiling
The system SHALL produce a multi-dimensional risk profile with distinct, independently assessed dimensions. No single composite numeric score SHALL be produced. Each dimension SHALL derive deterministically from observable evidence.

#### Scenario: Migration present elevates persistence risk
- **WHEN** a change includes a new or modified Alembic migration file
- **THEN** the `persistence_impact` dimension SHALL be `HIGH`

#### Scenario: Security/auth path touched elevates security risk
- **WHEN** a change modifies files whose paths contain canonical security/auth markers (e.g., `auth_`, `security`, `secrets`, `credentials`, `tokens`)
- **THEN** the `security_auth_impact` dimension SHALL be at least `LOW`

#### Scenario: Scheduler file touched elevates orchestration risk
- **WHEN** a change modifies a file under the orchestration or scheduling service paths
- **THEN** the `provider_orchestration` dimension SHALL be at least `LOW`

#### Scenario: Destructive migration operation detected elevates risk conservatively
- **WHEN** an actual destructive SQL DDL operation (DROP TABLE, DROP COLUMN, TRUNCATE) is detected within a migration file's content
- **THEN** the `destructive_operations` dimension SHALL be `PRESENT`
- **AND** the `persistence_impact` dimension SHALL be `HIGH`

#### Scenario: Natural-language mention of deletion does not trigger destructive risk
- **WHEN** a non-migration source file contains the word "delete" in documentation, comments, or natural language
- **THEN** the `destructive_operations` dimension SHALL remain `NONE`

#### Scenario: High complexity but low security risk keeps dimensions distinct
- **WHEN** a change has HIGH complexity (many files, cross-module) but no auth/security paths are touched
- **THEN** `security_auth_impact` SHALL be `NONE` regardless of complexity level

#### Scenario: Low complexity but high security sensitivity not collapsed
- **WHEN** a change modifies 1 auth-related file triggering `HIGH` security impact but has LOW overall complexity
- **THEN** `security_auth_impact` SHALL remain distinct from complexity and SHALL report `HIGH`

#### Scenario: Review sensitivity flag set when any dimension is HIGH
- **WHEN** any risk dimension in the profile is at `HIGH`
- **THEN** `requires_review_sensitivity` SHALL be `True` in the classification snapshot

### Requirement: Structural Task Surface Classification
The system SHALL classify the structural surface of a change into one canonical `TaskSurfaceKind` value from observable file paths. A change SHALL be classified as `MIXED` when it touches multiple surface categories.

#### Scenario: Test-only change classified distinctly from production
- **WHEN** a change modifies only files under the `tests/` directory
- **THEN** the surface kind SHALL be `TESTS_ONLY`
- **AND** complexity SHALL reflect test scope but `provider_orchestration` risk SHALL be `NONE`

#### Scenario: Migration change classified as migration surface
- **WHEN** a change modifies one or more files under `alembic/versions/`
- **THEN** the surface kind SHALL be `MIGRATION_SCHEMA`

#### Scenario: Config-only change classified as config surface
- **WHEN** a change modifies only configuration files (`config/*.yaml`, `.env`, `pyproject.toml`)
- **THEN** the surface kind SHALL be `CONFIG_ONLY`

#### Scenario: Cross-surface change classified as MIXED
- **WHEN** a change touches both migration files and backend service code
- **THEN** the surface kind SHALL be `MIXED`
- **AND** all individually detected surfaces SHALL be recorded in `surface_details`

### Requirement: Pre-Execution and Post-Materialization Classification Stages
The system SHALL support two classification stages: `PRE_EXECUTION` (before any diff exists, from OpenSpec metadata) and `POST_MATERIALIZATION` (from actual `git diff --name-only`).

#### Scenario: Pre-execution classification created at intake
- **WHEN** a change reaches `READY` status or a job is admitted
- **THEN** a `TaskClassificationSnapshot` with `stage=PRE_EXECUTION` SHALL be created from available OpenSpec metadata
- **AND** the snapshot SHALL record `classification_completeness` reflecting available vs missing evidence

#### Scenario: Pre-execution classification does not fabricate LOW when evidence is thin
- **WHEN** pre-execution evidence is limited to change name and proposal metadata without concrete file or module information
- **THEN** the classification SHALL NOT silently produce `LOW` complexity
- **AND** `classification_completeness` SHALL be `MINIMAL` or `PARTIAL` with missing signals enumerated

#### Scenario: Post-materialization classification references pre-execution
- **WHEN** an implementation attempt produces a candidate diff and a post-materialization classification is created
- **THEN** the snapshot SHALL reference the pre-execution snapshot via `pre_execution_snapshot_id`
- **AND** `breadth_mismatch_detected` SHALL be set when actual scope exceeds planned scope

#### Scenario: Actual diff exceeds planned scope surfaces mismatch
- **WHEN** a pre-execution classification estimated MEDIUM complexity but the actual diff touches more modules and a migration is present
- **THEN** the post-materialization snapshot SHALL have `breadth_mismatch_detected=True`
- **AND** the post-materialization complexity SHALL reflect the actual observed scope

#### Scenario: Actual diff is smaller than planned scope
- **WHEN** the actual diff touches fewer files than the pre-execution estimate anticipated
- **THEN** the post-materialization classification SHALL reflect the actual scope
- **AND** the pre-execution snapshot SHALL remain unchanged and historically interpretable

#### Scenario: Re-planning produces new pre-execution snapshot
- **WHEN** a change is re-planned with new or revised OpenSpec artifacts
- **THEN** a new `PRE_EXECUTION` snapshot SHALL be created
- **AND** the new snapshot SHALL be distinguishable from the prior pre-execution snapshot by its snapshot ID

### Requirement: Classification Explainability
Every classification result SHALL include the signals, rule identifiers, evidence sources, and classifier version used to produce it, such that the result is fully reconstructable.

#### Scenario: Snapshot records contributing signals
- **WHEN** a classification snapshot is produced
- **THEN** the snapshot SHALL include `signals` documenting file count, top-level directories, migration detected, security paths detected, and every contributing observable
- **THEN** the snapshot SHALL include `rule_identifiers` listing each rule that contributed to the classification

#### Scenario: Snapshot records evidence source
- **WHEN** a classification snapshot is produced
- **THEN** the snapshot SHALL record `evidence_source` as `OPENSPEC_METADATA`, `GIT_DIFF`, or `HYBRID`
- **THEN** the snapshot SHALL record `classifier_version` identifying the ruleset version used

#### Scenario: Classification can be reconstructed from snapshot data
- **WHEN** the same canonical inputs and classifier version are replayed
- **THEN** the system SHALL produce the same classification values

### Requirement: Classifier Versioning and Historical Stability
The system SHALL version classification rules via a `classifier_version` string recorded on each snapshot. Historical snapshots SHALL remain immutable and interpretable when the classifier version changes.

#### Scenario: Classifier version change does not alter historical snapshots
- **WHEN** the classifier is updated from version `1.0.0` to `1.1.0`
- **THEN** snapshots created with version `1.0.0` SHALL retain their original classification values and version marker

#### Scenario: Same inputs with same version produce same classification
- **WHEN** classification is performed twice with identical inputs and identical `classifier_version`
- **THEN** the resulting classification values SHALL be identical

#### Scenario: Snapshot identity is distinct from classifier version
- **WHEN** a new snapshot is created for a re-planned change using the same `classifier_version`
- **THEN** the snapshot SHALL have a distinct snapshot ID from any prior snapshot
- **AND** `classifier_version` SHALL remain the same if rules did not change

### Requirement: Fail-Closed and Unknown Handling
The system SHALL fail closed when evidence is incomplete: it SHALL NOT fabricate certainty, SHALL allow `UNKNOWN`/`INCOMPLETE` values, and SHALL expose missing signals.

#### Scenario: Missing canonical inputs produces UNKNOWN
- **WHEN** classification is requested but no OpenSpec metadata, no diff, and no file paths are available
- **THEN** complexity SHALL be `UNKNOWN`
- **AND** `classification_completeness` SHALL be `MINIMAL`
- **AND** missing signals SHALL be enumerated

#### Scenario: Classification persistence failure is observable
- **WHEN** the classifier produces a valid classification but persistence to the `task_classification_snapshots` table fails
- **THEN** the failure SHALL be surfaced as an observable error
- **AND** no fabricated successful classification SHALL be recorded

#### Scenario: Legacy work item lacking sufficient metadata is handled truthfully
- **WHEN** classification is attempted for a pre-existing work item with no OpenSpec metadata, no diff capture, and no structural evidence
- **THEN** the snapshot SHALL be marked `is_legacy=True`
- **AND** classification SHALL be `UNKNOWN` with reasons

### Requirement: Non-Interference with Existing Systems
The classifier SHALL produce classification facts only. It SHALL NOT select providers, select models, alter routing, alter retry policies, alter reviewer independence, or alter scheduler admission.

#### Scenario: Classification result exists but routing is unchanged
- **WHEN** a classification snapshot exists for a job
- **AND** the scheduler or provider selection evaluation runs
- **THEN** provider selection SHALL follow its existing policy rules without consulting the classification snapshot

#### Scenario: Classifier consumes zero inference tokens
- **WHEN** the classifier executes
- **THEN** no external provider API call SHALL be made
- **AND** no inference quota SHALL be consumed

#### Scenario: Reviewer role requirement recorded without selecting reviewer
- **WHEN** a classification snapshot records `requires_review_sensitivity=True`
- **THEN** the reviewer selection policy SHALL NOT be altered by the classifier
- **AND** the sensitivity flag SHALL be available for downstream consumers to read

#### Scenario: Existing TaskClass remains separate from classification profile
- **WHEN** both a `TaskClass` (e.g., `ROUTINE_IMPLEMENTATION`) and a `TaskClassificationSnapshot` exist for a job
- **THEN** the `TaskClass` SHALL retain its existing provider/execution semantics
- **AND** the snapshot SHALL not overwrite or redefine the `TaskClass`

### Requirement: Persistence and Stable References
The system SHALL persist classification snapshots as durable records in PostgreSQL. Classification SHALL be stored at the change or job lifecycle level (not duplicated per attempt). Stable identifiers SHALL be available for downstream telemetry correlation.

#### Scenario: Snapshot persisted at job level
- **WHEN** a classification snapshot is created for a job
- **THEN** the job SHALL reference the snapshot via `classification_snapshot_id`

#### Scenario: Snapshot persisted at change level
- **WHEN** a classification snapshot is created for a change (pre-execution)
- **THEN** the change record MAY reference the latest snapshot via `latest_classification_snapshot_id`

#### Scenario: Classification survives restart
- **WHEN** the system restarts
- **THEN** previously persisted classification snapshots SHALL be recoverable from the database with their full classification data

#### Scenario: Attempts reference classification through job
- **WHEN** telemetry or downstream consumers need the classification used during an attempt
- **THEN** the attempt's classification SHALL be retrievable via `job_attempts → jobs → task_classification_snapshots` without duplicating classification data per attempt

#### Scenario: Stable identifier available for telemetry correlation
- **WHEN** a classification snapshot is persisted
- **THEN** the snapshot SHALL have a stable `id` that can be referenced by telemetry records
- **AND** the `classifier_version` SHALL be recorded for versioned correlation

### Requirement: Evidence Precedence and Rule Centralization
The system SHALL apply deterministic evidence precedence: observed structural evidence overrides canonical path/surface rules, which override weak textual hints. Surface/path classification rules SHALL be centralized in a single versioned module, not scattered throughout the classifier.

#### Scenario: Observed diff overrides metadata classification
- **WHEN** pre-execution metadata suggests a `DOCS_ONLY` surface but actual diff includes backend service code
- **THEN** the post-materialization classification SHALL reflect the actual diff surface
- **AND** the mismatch SHALL be recorded

#### Scenario: Keyword in change name does not override file path evidence
- **WHEN** a change name contains "refactor" but the actual diff is a 2-file isolated fix with no schema changes
- **THEN** complexity SHALL be determined from the actual diff (LOW) not from the name keyword

#### Scenario: Destructive risk requires actual migration operation evidence
- **WHEN** a file path contains "delete" in its name but the file content is a routine update with no destructive SQL
- **THEN** the `destructive_operations` dimension SHALL be `NONE`
