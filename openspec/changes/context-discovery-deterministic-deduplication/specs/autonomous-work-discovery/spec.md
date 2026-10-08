# Autonomous Work Discovery Specification Delta

## ADDED Requirements

### Requirement: Context Discovery Deterministic Deduplication
`ContextDiscoveryService.discover_context_pure(project_id)` SHALL return at most one discovered `BacklogItem` projection for each `(project_id, item_key)` tuple prior to persistence, deterministically selecting the highest precedence state when duplicate evidence appears across canonical sources.

#### Scenario: Duplicate milestone key in ROADMAP produces single discovered projection
- **GIVEN** a canonical `ROADMAP.md` containing multiple sections referencing the same item key `019-server-runtime-deployment`
- **WHEN** `discover_context_pure("mini-me")` is invoked
- **THEN** it SHALL return exactly one `BacklogItem` with `item_key="019-server-runtime-deployment"`
- **AND** the returned item SHALL reflect the highest precedence status (e.g. `COMPLETED` over `BACKLOG`)
- **AND** `discover_context("mini-me")` SHALL persist exactly one row without violating `uq_backlog_items_project_key`.

#### Scenario: Repeated context discovery execution is idempotent
- **GIVEN** a project with duplicate context evidence in `ROADMAP.md`
- **WHEN** `discover_context("mini-me")` is executed multiple times in succession
- **THEN** it SHALL succeed without raising `IntegrityError`
- **AND** exactly one `BacklogItem` row per `(project_id, item_key)` SHALL exist in persistence
- **AND** existing persisted terminal state SHALL not be resurrected or mutated.
