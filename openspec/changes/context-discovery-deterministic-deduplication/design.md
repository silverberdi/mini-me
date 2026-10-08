# Design: Context Discovery Deterministic Deduplication

## Architectural Decisions

### 1. Pure Function Unique Output Guarantee
`ContextDiscoveryService.discover_context_pure(project_id)` will be updated to guarantee that its returned list of `BacklogItem` objects contains at most one entry per `item_key`. Deduplication happens strictly in-memory during discovery before any database or persistence operations occur.

### 2. Deterministic Status Precedence Hierarchy
When duplicate milestone keys appear in source context files (such as `ROADMAP.md` or `BACKLOG.md`), status resolution follows a explicit precedence hierarchy:
- `COMPLETED` (Rank 5)
- `CANCELLED` (Rank 4)
- `READY` (Rank 3)
- `BLOCKED` (Rank 2)
- `IN_PROGRESS` / preparing context states (Rank 1)
- `BACKLOG` (Rank 0)

When a duplicate `item_key` is discovered:
- If the new observation has a strictly higher status rank, the discovered `BacklogItem` projection adopts the higher status and updated non-empty metadata.
- If status ranks are equal, the first observation's primary identity and title are preserved, retaining stable metadata.

### 3. Preservation of Traversal Ordering
Items are stored in an ordered dictionary/accumulation map keyed by `item_key`. The iteration order of returned `BacklogItem`s matches the order of first appearance across canonical sources.

### 4. Defense-in-Depth Persistence & Terminal State Protection
- Database schema constraint `uq_backlog_items_project_key` remains unchanged.
- `discover_context()` receives the unique projections from `discover_context_pure()`. For each item:
  - If a DB record already exists in terminal status (`COMPLETED` or `CANCELLED`), the existing terminal DB state is preserved and warnings logged if source evidence contradicts terminal status.
  - Otherwise, `discover_context()` updates or inserts the record cleanly without triggering `IntegrityError`.
