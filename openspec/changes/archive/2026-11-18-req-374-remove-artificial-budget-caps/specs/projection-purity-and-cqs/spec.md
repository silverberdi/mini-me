## MODIFIED Requirements

### Requirement: Pure HTTP GET/HEAD Endpoint Purity and Non-Locking Reads
The system SHALL enforce that all HTTP GET and HEAD endpoints classified as Queries operate strictly as side-effect-free operations, SHALL execute zero database inserts, updates, deletes, or event emissions, and SHALL NOT request write-intent database locks (`SELECT ... FOR UPDATE` or `get_for_update()`). Any retained usage query SHALL expose observed provider usage/cost evidence only and SHALL NOT calculate or return artificial daily/monthly cap headroom.

#### Scenario: HTTP GET budget usage returns metrics without acquiring write lock
GIVEN a client requesting a retained spend-usage query
WHEN the API processes the request
THEN it SHALL fetch only persisted provider usage/cost evidence using non-locking read queries
AND SHALL NOT expose legacy daily/monthly caps or headroom
AND SHALL NOT call `get_for_update()` or execute `SELECT ... FOR UPDATE`
AND the database state SHALL remain unchanged.

#### Scenario: HTTP GET openrouter status evaluates status without write lock
GIVEN a client requesting HTTP GET `/providers/openrouter/status`
WHEN the API processes the request
THEN it SHALL report only configured provider identity and observable provider facts available from a supported source
AND SHALL NOT query or expose legacy budget policy, daily/monthly cap, or headroom
AND SHALL NOT acquire write-intent row locks.

#### Scenario: HTTP GET health endpoint checks database without mutating catalog
GIVEN a client requesting HTTP GET `/health` or HEAD `/health`
WHEN the health endpoint checks database connectivity
THEN it SHALL execute a read-only probe (`SELECT 1`)
AND SHALL NOT attempt schema migration, state repair, or record insertion.
