## Why

mini me currently classifies tasks for provider selection (`TaskClass`) and local worker safety (`ForbiddenSurfaceKind`), but lacks a deterministic, explainable classification of the inherent complexity, multidimensional risk, and structural surface of work itself. This gap prevents later changes (`ai-provider-model-capability-selection`, `execution-attempt-effectiveness-telemetry`) from consuming stable, provider-agnostic classification signals. Introducing these signals now -- deterministically and without making routing decisions -- ensures downstream changes can correlate outcomes with task characteristics on a solid foundation.

## What Changes

- Introduce a `TaskComplexity` taxonomy (LOW, MEDIUM, HIGH) based on observable change scope and breadth
- Introduce a multi-dimensional `TaskRiskProfile` with independent dimensions: code-change breadth, architectural impact, persistence/migration risk, security/auth impact, production/runtime impact, provider/orchestration impact, destructive operations, deployment/config impact
- Introduce `TaskSurfaceKind` classifying what shape the change takes (docs-only, tests-only, config-only, migration/schema, backend/service, UI/frontend, infrastructure/deployment, provider-integration, orchestration-lifecycle, security/auth, mixed)
- Provide a `TaskComplexityRiskClassifier` service producing deterministic `TaskClassificationSnapshot` records from observable evidence
- Support two classification stages: **pre-execution estimate** (from OpenSpec scope, before any diff exists) and **post-materialization observation** (from actual `git diff --name-only` surface analysis), with traceable relationship between them
- Centralize and version all path/keyword surface rules in a single canonical structure, not scattered throughout the classifier
- Define deterministic evidence precedence: observed structural evidence > canonical path/surface rules > weak textual hints; keyword heuristics never override stronger evidence
- Persist classification snapshots at the change/job level (not duplicated per attempt) in a new `task_classification_snapshots` table with FKs to `changes` and `jobs`
- Minimal classifier versioning: `classifier_version` on each snapshot, rules live in code (not a database rules engine)
- Fail-closed: incomplete evidence produces `UNKNOWN`/`INCOMPLETE`, never silently classified LOW
- Explicitly document that existing `TaskClass` (provider/execution semantics) remains separate and unchanged

## Capabilities

### New Capabilities
- `task-complexity-risk-classification`: Deterministic, explainable, versioned classification of change/task complexity, multi-dimensional risk, and structural surface from observable evidence. Produces `TaskClassificationSnapshot` records with stable identifiers for downstream consumption. Does NOT select provider, model, effort, or route.

### Modified Capabilities
None. No existing capability owns complexity/risk/surface classification of work. Existing `TaskClass` in `provider-efficiency-and-anti-loop` classifies attempt type for provider selection -- orthogonal and complementary, not replaced or redefined. Existing `ForbiddenSurfaceKind` in the local worker is a safety allowlist/denylist for a single execution path, not a general classifier.

## Impact

- New domain enums: `TaskComplexity`, `TaskSurfaceKind`, `ClassificationStage`, `ClassificationCompleteness`
- New domain models: `TaskRiskProfile`, `TaskClassificationSnapshot`, `ClassifiedRiskDimension`
- New service: `TaskComplexityRiskClassifier` (deterministic rules, zero inference tokens)
- New DB table: `task_classification_snapshots` (Alembic migration 022)
- Optional FK columns: `classification_snapshot_id` on `jobs`; `latest_classification_snapshot_id` on `changes`
- Centralized surface-rule configuration module (versioned rules, not scattered heuristics)
- Zero impact on provider selection, scheduler admission, retry policy, or reviewer independence
- No UI changes; no human validation scenarios required
- No provider cost (zero inference tokens)