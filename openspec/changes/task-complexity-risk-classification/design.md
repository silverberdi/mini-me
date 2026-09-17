## Context

The existing classification landscape is described in proposal.md. Key architectural constraints:
- `TaskClass` (9 values, `domain/enums.py:555`) classifies attempt type for provider selection (Codex vs Antigravity). It lives on `job_attempts` and is computed by `TaskClassifier`. This change does NOT modify it.
- `ForbiddenSurfaceKind` (8 values, `local_worker/task_classes.py:138`) is a safety allowlist/denylist for the local Ollama worker path. It lives outside the core classification system and has no pre-execution stage.
- Git diff surface analysis exists in `outcome_governance.py:86-116` for completion verification, not classification.
- PostgreSQL is the only operational DB. Alembic migrations are sequential and versioned. The latest migration is `021_provider_probe_cooldown_state`.
- Domain models use Pydantic v2 `BaseModel`. ORM models follow the pattern: `String(64)` PK, `String(64)` FK, `DateTime(timezone=True)` timestamps, `JSON` with `server_default="{}"` in migrations, `Boolean` with `server_default=sa.false()`.
- Domain enums extend `str, Enum` for persistence as strings.

## Goals / Non-Goals

**Goals:**
- Deterministic complexity classification (LOW/MEDIUM/HIGH/UNKNOWN) from observable evidence
- Multi-dimensional risk profile with independent dimensions
- Structural surface classification (`TaskSurfaceKind`)
- Two-stage classification: PRE_EXECUTION (from OpenSpec) and POST_MATERIALIZATION (from diff)
- Centralized, versioned surface-rule configuration module
- Evidence precedence: observed structural > canonical path rules > weak textual hints
- Fail-closed: UNKNOWN when evidence is insufficient; no silent LOW fabrication
- Stable snapshot IDs and classifier version for downstream correlation
- Classification stored at change/job level, not duplicated per attempt

**Non-Goals:**
- Provider selection, model selection, effort selection
- Adaptive routing, benchmark calibration
- Telemetry implementation, dashboard, alerting
- AI/LLM-based authoritative classification
- Generalized policy engine or database-stored rules engine
- Replacing or redefining existing `TaskClass` semantics
- Broad repository refactor

## Decisions

### D1: Classification at Change/Job Level, Not Per-Attempt

Complexity and risk are properties of the *work*, not the *attempt*. Storing classification per `job_attempt` would semantically duplicate the same classification across multiple attempts. All attempts within the same job share the same task.

**Alternative considered:** Per-attempt storage (like existing `TaskClass`). Rejected because `TaskClass` reflects *attempt type* (remediation vs fresh implementation) which genuinely varies across attempts, whereas complexity/risk is invariant for the same job.

**Implementation:** New `task_classification_snapshots` table with optional FK columns on `changes` and `jobs`. Attempts reference the classification via `jobs.classification_snapshot_id`.

### D2: Single Table with Stage Discriminator, Not Separate Tables

Both pre-execution and post-materialization classifications share the same schema. They differ only in `stage`, `evidence_source`, and signal completeness. A single table with a stage discriminator avoids schema duplication while allowing FK self-references (`pre_execution_snapshot_id`).

**Alternative considered:** Separate tables (`pre_execution_classifications`, `post_materialization_classifications`). Rejected as over-engineering; the data shape is identical and the relationship is a simple predecessor link.

### D3: Rules in Code, Not in Database

Classification rules live in a single centralized Python module (`classification_rules.py`), not as database-stored rule entries. This keeps the change bounded (no rules engine, no rule CRUD API) and matches the existing pattern of `TaskClassifier` and `local_worker/task_classes.py`.

**Alternative considered:** Database-stored rules engine for runtime configurability. Rejected as premature; current architecture has no precedent for stored rules. If needed, a separate change can introduce a rules engine.

### D4: Three-Tier Evidence Precedence

```
Tier 1: Observed structural evidence
  → git diff file paths, migration file presence, actual code surface

Tier 2: Canonical path/surface rules
  → centralized versioned module mapping paths to risk dimensions
  → e.g., "touching src/minime/services/provider_policy_service.py → provider_orchestration risk"

Tier 3: Weak planning/textual hints
  → OpenSpec proposal text, change name keywords, task descriptions
  → NEVER override Tier 1 or Tier 2 evidence
  → Only contribute when no stronger evidence exists
```

### D5: Centralized Surface Rules, Not Scattered Heuristics

All path and keyword surface rules are centralized in a single module (`src/minime/services/classification_rules.py`) with the following structure:

```python
# Versioned rule set
CLASSIFIER_VERSION = "1.0.0"

# Tier 2: Canonical path-to-risk mappings (versioned, centralized)
PATH_RISK_SURFACES: dict[str, list[RiskDimension]] = {...}
PATH_SURFACE_MAPPINGS: dict[str, TaskSurfaceKind] = {...}
CONFIG_FILE_PATTERNS: tuple[str, ...] = (...)
SECURITY_PATH_MARKERS: tuple[str, ...] = (...)
PROVIDER_ORCHESTRATION_PATH_MARKERS: tuple[str, ...] = (...)
DEPLOYMENT_PATH_MARKERS: tuple[str, ...] = (...)

# Tier 3: Weak textual hints (used only when Tier 1+2 exhausted)
WEAK_SURFACE_HINTS: dict[str, TaskSurfaceKind] = {...}
```

This avoids scattering string heuristics throughout the classifier and makes rule versions explicit and auditable.

### D6: Destructive Risk Requires Actual Operation Evidence

The word "delete" in a filename, comment, or natural-language description does not trigger destructive risk. Only actual observable destructive operations count:

| Evidence type | Qualifies? | Example |
|---|---|---|
| `DROP TABLE`, `DROP COLUMN`, `DROP INDEX` in migration SQL | Yes | `op.drop_table("foo")` |
| `TRUNCATE` in migration SQL | Yes | `op.execute("TRUNCATE ...")` |
| `sa.Column(...).drop()` in migration | Yes | Column drop via SQLAlchemy |
| Path named `delete_something.py` | No | Just a filename |
| Natural language "we should delete X" | No | Commentary |
| `DELETE` in application code | No | Normal CRUD |

### D7: Pre-Execution Uncertainty Explicitly Represented

Pre-execution classification captures what it *doesn't* know:

```python
class PreExecutionClassification:
    complexity: TaskComplexity  # May be UNKNOWN
    risk_profile: TaskRiskProfile
    surface_kind: TaskSurfaceKind  # May be UNKNOWN
    classification_completeness: ClassificationCompleteness  # COMPLETE/PARTIAL/MINIMAL
    missing_signals: list[str]  # e.g., ["no diff available", "task scope not fully specified"]
    evidence_source: str  # "OPENSPEC_METADATA"
```

**Rule:** Pre-execution MUST NOT fabricate LOW when evidence is thin. If OpenSpec metadata says the change touches "auth" but no file paths are known, complexity may be UNKNOWN with PARTIAL completeness.

### D8: Snapshot Identity ≠ Classifier Version

- `snapshot.id`: UUID identifying *this particular classification observation*. Changes on every snapshot creation (including re-planning with same classifier version).
- `snapshot.classifier_version`: The `CLASSIFIER_VERSION` constant at the time the snapshot was created. Multiple snapshots may share the same version.
- Re-planning creates a new snapshot (new `id`) but only increments `classifier_version` if the rules code actually changed.

### D9: design.md Presence Is Not Complexity

The mere presence of a `design.md` file in an OpenSpec change does not indicate architectural complexity. What matters is the *content* of design.md: whether it declares cross-module changes, interface redesigns, new architectural patterns, or structural subsystem contract changes.

Implementation: When classifying pre-execution, the classifier may inspect design.md *content* for structural signals (e.g., "cross-module", "architectural change", "interface redesign") but never uses file existence alone as a signal.

### D10: Existing TaskClass Remains Separate

The existing `TaskClass` enum (ROUTINE_IMPLEMENTATION, ORDINARY_REMEDIATION, etc.) classifies *what kind of attempt* the system needs for provider selection. `TaskComplexityRiskClassifier` classifies *what the work looks like* structurally. They answer different questions for different consumers.

| Question | Answered by | Consumer |
|---|---|---|
| What provider should run this attempt? | `TaskClass` | `ProviderPolicyService` |
| How complex/risky is this work? | `TaskClassificationSnapshot` | Later: selector, telemetry |
| What surface does this change touch? | `TaskClassificationSnapshot` | Later: selector, dashboard |

No integration between these two systems is in scope for this change.

## Persistence Design

### Table: `task_classification_snapshots`

Aligned with canonical conventions from existing models (PK: `String(64)`, FK: `String(64)` with `ondelete=CASCADE`, timestamps: `DateTime(timezone=True)`, JSON: `JSON` with `server_default`, Boolean: `Boolean` with `server_default=sa.false`):

```sql
CREATE TABLE task_classification_snapshots (
    id                           VARCHAR(64) PRIMARY KEY,
    change_id                    VARCHAR(64) REFERENCES changes(id) ON DELETE SET NULL,
    job_id                       VARCHAR(64) REFERENCES jobs(id) ON DELETE SET NULL,
    stage                        VARCHAR(32) NOT NULL,
    classifier_version           VARCHAR(16) NOT NULL,
    complexity                   VARCHAR(16) NOT NULL,
    risk_profile                 JSON NOT NULL DEFAULT '{}',
    surface_kind                 VARCHAR(32) NOT NULL,
    surface_details              JSON NOT NULL DEFAULT '{}',
    signals                      JSON NOT NULL DEFAULT '{}',
    rule_identifiers             JSON NOT NULL DEFAULT '[]',
    evidence_source              VARCHAR(32) NOT NULL,
    classification_completeness  VARCHAR(16) NOT NULL,
    missing_signals              JSON NOT NULL DEFAULT '[]',
    pre_execution_snapshot_id    VARCHAR(64) REFERENCES task_classification_snapshots(id) ON DELETE SET NULL,
    breadth_mismatch_detected    BOOLEAN NOT NULL DEFAULT FALSE,
    is_legacy                    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at                   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### FK Additions to Existing Tables

```sql
ALTER TABLE jobs ADD COLUMN classification_snapshot_id VARCHAR(64)
    REFERENCES task_classification_snapshots(id) ON DELETE SET NULL;
ALTER TABLE changes ADD COLUMN latest_classification_snapshot_id VARCHAR(64)
    REFERENCES task_classification_snapshots(id) ON DELETE SET NULL;
```

Both are nullable: classification may not exist for legacy work, and `SET NULL` preserves the referencing row when a snapshot is cleaned up.

### Migration: `022_task_classification_snapshots`

Follows the canonical Alembic pattern (sequential revision, `op.create_table`, `op.add_column`, `op.create_index`).

## Service Architecture

### `TaskComplexityRiskClassifier`

Single service class with two entry points:

```python
class TaskComplexityRiskClassifier:
    def classify_pre_execution(
        self,
        change: Change,
        tasks: list[OpenSpecTask],
        proposal_text: str | None = None,
    ) -> TaskClassificationSnapshot: ...

    def classify_post_materialization(
        self,
        pre_execution_snapshot: TaskClassificationSnapshot | None,
        diff_file_paths: list[str],
        migration_files: list[str] | None = None,
        design_content: str | None = None,
    ) -> TaskClassificationSnapshot: ...
```

Both methods delegate to internal deterministic rule functions:
- `_extract_complexity(signals) -> TaskComplexity`
- `_extract_risk_profile(signals) -> TaskRiskProfile`
- `_extract_surface_kind(signals) -> TaskSurfaceKind`
- `_extract_signals(diff_paths, ...) -> dict` (shared between stages)

### Lifecycle Integration Points

1. **Pre-execution**: Triggered when a change transitions to `READY` or at job admission in `orchestration_service.py` / `execution_pipeline.py`
2. **Post-materialization**: Triggered after implementation produces a candidate diff, in `outcome_governance.py` or `execution_pipeline.py` after `git diff --name-only` is available

### `classification_rules.py` Module

Centralized, versioned rule configuration (see D5). Exports:
- `CLASSIFIER_VERSION: str`
- `PATH_RISK_SURFACES: dict`
- `PATH_SURFACE_MAPPINGS: dict`
- `CONFIG_FILE_PATTERNS: tuple`
- `SECURITY_PATH_MARKERS: tuple`
- `PROVIDER_ORCHESTRATION_PATH_MARKERS: tuple`
- `DEPLOYMENT_PATH_MARKERS: tuple`
- `DESTRUCTIVE_MIGRATION_PATTERNS: tuple`
- `WEAK_SURFACE_HINTS: dict` (Tier 3 only)

## Risks / Trade-offs

- **[Risk] Rule changes between versions may change classification for same work** → Mitigation: immutable historical snapshots with `classifier_version`; consumers can interpret changes in context
- **[Risk] Pre-execution classification may be wrong** → Mitigation: `classification_completeness` and `missing_signals` explicitly communicate uncertainty; post-materialization is the authoritative observation
- **[Risk] Path-based rules may miss cross-cutting impacts through imports** → Acceptable for MVP; import graph analysis is a future enhancement
- **[Trade-off] Centralized rules module vs distributed per-dimension rules** → Chose centralized for versioning simplicity and auditability; if the module grows too large, it can be split in a later version