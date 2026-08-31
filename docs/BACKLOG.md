# Product Backlog

## Delivered Items (Stages 001 – 015)

| ID | Stage | Outcome | Verification idea |
|---|---|---|---|
| MM-001 | 001 | PostgreSQL config + versioned schema | migrate/restart tests |
| MM-002 | 001 | Durable event/current-state core | transactional transition tests |
| MM-003 | 001 | Register projects with immutable repo binding | mismatch denial tests |
| MM-004 | 001 | Discover OpenSpec and enforce DoR | fixtures + invalid bindings |
| MM-005 | 001 | GitHub Issue/Project durable mapping foundation | mocked API + reconciliation |
| MM-006 | 001 | Status/health API/CLI | contract tests |
| MM-010 | 002 | Isolated Git worktree lifecycle | integration tests |
| MM-011 | 002 | Codex implementer adapter | fake + opt-in CLI smoke |
| MM-012 | 002 | Antigravity implementer adapter | fake + opt-in CLI smoke |
| MM-013 | 002 | Deterministic checks runner and diagnostics | pass/fail/timeout/redaction |
| MM-020 | 003 | Complementary review pipeline | seeded defect test |
| MM-021 | 003 | Bounded review correction loop | max-round tests |
| MM-030 | 004 | DeepSeek Direct independent audit | mock + opt-in live audit |
| MM-040 | 005 | Provider resilience, restart recovery & health | kill/restart E2E, fault injection |
| MM-041 | 005 | RUN/DRAIN/WAIT scheduler modes | scheduler simulations |
| MM-042 | 006 | OpenRouter drain fallback with model independence | distinct-model & budget tests |
| MM-043 | 007 | Agent continuation and handoff governance | ping-pong denial & handoff tests |
| MM-044 | 008 | Autonomous multi-stage orchestration coordinator | stage transition & gate tests |
| MM-045 | 009 | GitHub App runtime integration & PR preparation | GitHub App authentication tests |
| MM-046 | 010 | Governance and recovery hardening | transition key & identity tests |
| MM-047 | 011 | Preserved candidate remediation generations | generation increment & drift tests |
| MM-048 | 012 | Execution operations dashboard | API projections & UI visual tests |
| MM-050 | 013 | Container preview lifecycle (build/start/probe/teardown) | real Docker build & health probe test |
| MM-051 | 013 | Candidate authority binding `(head_sha, base_sha, image_digest)` | image digest authority & mutation tests |
| MM-052 | 013 | Guided UI validation workflow & scenarios | scenario runner & PASS/FAIL state tests |
| MM-053 | 013 | Stale validation invalidation & historical evidence | candidate drift / stale PASS tests |
| MM-054 | 013 | Preview restart/orphan reconciliation & isolation | restart recovery & foreign container guard |
| MM-055 | 013 | Dashboard integration for guided scenario validation | UI component & browser acceptance tests |
| MM-060 | 014 | TUI operator console (Textual) | interactive terminal navigation tests |
| MM-070 | 015 | Operator actions / control plane (retry/resume/reassign/gates) | mutation authority & auditability tests |

---

## Canonical Active & Future Roadmap Items (Stages 016 – 018)

| ID | Stage | Outcome | Verification idea |
|---|---|---|---|
| MM-080 | 016 (NEXT) | Autonomous queue & work selection (readiness/budget/capacity) | multi-change autonomous scheduling tests |
| MM-090 | 017 | PWA control center (rich web operator experience) | responsive web app & PWA acceptance |
| MM-100 | 018 | End-to-end self-operating development loop & SDLC metrics | full-cycle autonomous delivery & metrics |

Backlog items are planning units. OpenSpec `tasks.md` remains the implementation checklist for the active change; do not duplicate every task into GitHub Issues.
