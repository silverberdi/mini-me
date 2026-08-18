# Product Backlog

| ID | Outcome | Verification idea |
|---|---|---|
| MM-001 | PostgreSQL config + versioned schema | migrate/restart tests |
| MM-002 | Durable event/current-state core | transactional transition tests |
| MM-003 | Register projects with immutable repo binding | mismatch denial tests |
| MM-004 | Discover OpenSpec and enforce DoR | fixtures + invalid bindings |
| MM-005 | GitHub Issue/Project durable mapping foundation | mocked API + reconciliation |
| MM-006 | Status/health API/CLI | contract tests |
| MM-010 | Isolated Git worktree lifecycle | integration tests |
| MM-011 | Codex adapter | fake + opt-in CLI smoke |
| MM-012 | Antigravity adapter | fake + opt-in CLI smoke |
| MM-013 | deterministic checks/evidence | pass/fail/timeout |
| MM-020 | complementary review | seeded defect |
| MM-021 | bounded correction loop | max-round tests |
| MM-022 | durable human inbox/decisions | API/TUI acceptance |
| MM-030 | DeepSeek Direct audit | mock + opt-in live |
| MM-040 | failure taxonomy/retry/circuit breaker | deterministic fault injection |
| MM-041 | restart reconciliation | kill/restart E2E |
| MM-042 | RUN/DRAIN/WAIT | scheduler simulations |
| MM-043 | OpenRouter drain implementation/review | no-new-work + distinct-model tests |
| MM-044 | hard budget/provider privacy | denied-call assertions |
| MM-050 | containerized UI preview | build/up/health/down fixture |
| MM-051 | guided UI human validation | scenario + stale-candidate tests |
| MM-052 | candidate SHA/base/image identity | mutation/drift tests |
| MM-060 | draft PR lifecycle + human merge | GitHub integration test |
| MM-061 | production deployment/verification | container deployment fixture |
| MM-062 | closure/archive/sync/cleanup | end-to-end DoD test |
| MM-063 | metrics finalization | recomputation tests |

Backlog items are planning units. OpenSpec `tasks.md` remains the implementation checklist for the active change; do not duplicate every task into GitHub Issues.
