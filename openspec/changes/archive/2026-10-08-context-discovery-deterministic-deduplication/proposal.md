# Proposal: Context Discovery Deterministic Deduplication

## Problem
In `ContextDiscoveryService`, `discover_context_pure(project_id)` parses canonical project context sources such as `ROADMAP.md` and `BACKLOG.md`. When the same canonical milestone key appears multiple times in source files (e.g., `019-server-runtime-deployment` appearing as an active section header and later as a `DELIVERED` section header in `docs/ROADMAP.md`), `discover_context_pure()` currently yields multiple `BacklogItem` projections for the same `(project_id, item_key)`. When `discover_context()` attempts to persist these items in a single transaction, PostgreSQL fails with `IntegrityError` due to the `uq_backlog_items_project_key` unique constraint.

## Proposed Solution
Introduce deterministic deduplication within `discover_context_pure()` before items reach the persistence layer:
1. `discover_context_pure()` will accumulate discovered items keyed by `(project_id, item_key)` (or `item_key` for a project invocation).
2. When duplicate keys are observed, apply a deterministic precedence rule to select the authoritative `BacklogItem` projection: `COMPLETED` > `CANCELLED` > `READY` > `BLOCKED` > `IN_PROGRESS` / preparing states > `BACKLOG`.
3. Preserve original presentation/traversal order based on the first occurrence of each unique key.
4. Maintain `uq_backlog_items_project_key` in PostgreSQL as defense-in-depth.
5. Ensure `discover_context()` is strictly repeat-safe and idempotent when run multiple times against duplicate source evidence.

## Scope
- Deduplication of discovered items in `discover_context_pure()` prior to database persistence.
- Deterministic precedence rule for state selection when duplicate keys occur in discovery.
- Comprehensive regression tests for repeated headings, cross-source duplicates, and idempotency.

## Non-Goals / Out of Scope
- Modifying scheduler policy, queue scoring, or lifecycle transition matrices.
- Altering database schema or removing `uq_backlog_items_project_key`.
- Modifying source `ROADMAP.md` contents merely to hide parser defects.
- Changing terminal DB state preservation rules.
