# Proposal: 018.1 Provider Efficiency & Reviewer Independence Hardening

## Background & Why Now
Following the successful delivery of Stage 017 (`017-pwa-control-center`), an exhaustive provider-efficiency audit identified systemic operational defects in autonomous execution:
1. Codex productive attempt rate fell to 75% and Antigravity CLI productive rate was 0%, with 2 out of 5 attempts producing no measurable progress.
2. Unnecessary reassignment from Codex to Antigravity without validated justification, burning scarce Antigravity quota.
3. Two identical same-SHA retries where identical failures were executed repeatedly without new evidence.
4. Over 825 avoidable supervisor polling calls and busy-wait loops, which correlated directly with provider rate limits and exhaustion.
5. Superficial OpenSpec `tasks.md` bookkeeping and evidence synchronization triggered full-agent 10-minute LLM retries.
6. A dead-end in `CHECKS_FAILED` handling required manual supervisor intervention.
7. A confirmed reviewer-independence violation occurred when Antigravity modified candidate code and subsequently performed the complementary review.

Before general autonomous end-to-end execution (Stage 018.2) can be safely enabled, mini me must harden its provider selection policy, eliminate duplicate retries, protect scarce Antigravity quota, technically enforce reviewer independence, route failed checks through canonical remediation, and durably record efficiency telemetry.

---

## User & Operator Value
- **Economic & Predictable Provider Usage:** Routine implementation tasks default to Codex, reserving Antigravity for explicit premium architectural or visual recovery tasks.
- **Elimination of Infinite Retry Loops:** Same-SHA non-progress retries are suppressed, stopping wasteful quota consumption.
- **Fast In-Process Bookkeeping:** Tasks and evidence reconciliation run in milliseconds without consuming LLM invocations.
- **Guaranteed Reviewer Independence:** Candidates cannot be reviewed by agents that authored or modified their code.
- **Full Operational Observability:** Operator TUI and PWA surfaces display rich, real-time efficiency metrics and provider utilization facts directly from PostgreSQL.

---

## Scope & Boundaries
- **In Scope (018.1):**
  - Canonical provider roles and multi-factor selection policy.
  - Deterministic task classification model.
  - Retry budget (1 normal + 1 corrective) and same-SHA anti-loop suppression.
  - In-process lightweight reconciliation service.
  - Reviewer material-authorship tracking and independence enforcement.
  - Canonical `CHECKS_FAILED` remediation routing.
  - Anti-polling safeguards and process-wait patterns.
  - PostgreSQL efficiency metrics schema, repository, and APIs.
  - TUI and PWA Provider Efficiency views.
  - Historical 017 review governance repair.
  - Live proving pilot verifying hard efficiency gates.
- **Out of Scope (Future 018 Slices):**
  - General autonomous queue drain and multi-stage self-operating loops (018.2).
  - Autonomous post-merge archive and portfolio closure (018.3).
  - Multi-project SDLC metrics aggregations (018.4).

---

## Acceptance Criteria & Hard Gates
1. Antigravity routine implementation count = 0.
2. Antigravity assignment without explicit premium reason code = 0.
3. Same-SHA duplicate full-provider retries = 0.
4. Bookkeeping-only full-LLM retries = 0.
5. Reviewer independence violations = 0.
6. Busy-wait status polling loops = 0.
7. Codex productive attempt ratio >= 75%.
8. Provider exhaustion immediate reassign loops = 0.
9. 018.1 self-hosting native percentage >= 60%.
