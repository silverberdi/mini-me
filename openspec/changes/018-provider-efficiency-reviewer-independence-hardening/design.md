# Design: 018.1 Provider Efficiency & Reviewer Independence Hardening

## Architecture & System Overview
This design implements a deterministic, multi-factor provider governance engine, lightweight reconciliation, reviewer independence enforcement, anti-loop heuristics, and durable efficiency telemetry.

```text
               Work Discovery / Queue Item / Stage
                               ↓
                 Deterministic Task Classifier
         (ROUTINE, TEST_FIX, BOOKKEEPING, ARCHITECTURE, ...)
                               ↓
                Multi-Factor Provider Selector
     (Codex Workhorse / AG Premium Reasons / Quota / DRAIN)
                               ↓
    ┌──────────────────────────┴──────────────────────────┐
    │                                                     │
Bookkeeping / Evidence Sync                      Routine Implementation / Fix
    │                                                     │
Lightweight Reconciliation                     Codex Execution (Attempt 1)
(In-Process, 0 LLM Cost)                                  ↓
    │                                              Checks Execution
    │                                                     ↓
    │                                        PASS? ──No──> Remediation
    │                                         │          (Max 1 retry before
    │                                         │           Root-Cause Check)
    │                                         │                   │
    │                                        Yes          Same-SHA Repeated?
    │                                         │                   │
    │                                         │          Yes: SAME_SHA_SUPPRESSED
    │                                         │          No: Corrective Retry
    └──────────────────────────┬──────────────┘
                               ↓
                     Candidate Frozen
                               ↓
               Reviewer Independence Evaluation
      (eligible_reviewers = configured - material_authors)
                               ↓
                   Author-Independent Review
                               ↓
                     DeepSeek Direct Audit
                               ↓
                     Efficiency Telemetry
                  (Persisted in PostgreSQL)
                               ↓
                     TUI & PWA Telemetry UI
```

---

## Key Design Components

### 1. Deterministic Task Classification (`TaskClassifier`)
Evaluates deterministic signals rather than opaque LLM prompts:
- **`ROUTINE_IMPLEMENTATION`**: Standard feature implementation or task execution.
- **`ORDINARY_REMEDIATION`**: Review findings or minor check failures.
- **`TEST_FIX`**: Isolated test assertion failures.
- **`BOOKKEEPING_RECONCILIATION`**: `tasks.md` checkbox sync, manifest updates, metadata reconciliation.
- **`EVIDENCE_RECONCILIATION`**: Diagnostic artifact updates without product code changes.
- **`ARCHITECTURE`**: Explicit cross-cutting architectural changes or framework updates.
- **`UX_VISUAL_QA`**: Visual UI validation scenarios.
- **`PLATFORM_RECOVERY`**: Docker/compose failures, port collisions, git lock conflicts.
- **`SPECIALIZED`**: Explicit domain-constrained tasks.

### 2. Provider Roles & Multi-Factor Selection (`ProviderPolicyService`)
- **Codex Default Workhorse:** Default for `ROUTINE_IMPLEMENTATION`, `ORDINARY_REMEDIATION`, `TEST_FIX`. Antigravity is ineligible (`PREMIUM_PROVIDER_NOT_REQUIRED`).
- **Antigravity Premium Governed Resource:** Allowed only with explicit reason code (`ARCHITECTURE_REQUIRED`, `UX_VISUAL_QA`, `PLATFORM_RECOVERY`, `CODEX_NON_CONVERGENCE`, `SPECIALIZED_REASON`).
- For `CODEX_NON_CONVERGENCE`: Requires verifiable proof of:
  1. Initial Codex attempt completed.
  2. One corrective retry completed.
  3. Root-cause classification performed.
  4. Lightweight reconciliation evaluated and not applicable.
- **Exhaustion Handling:** On quota limit, provider transitions to `DRAIN`. No immediate reassign loops to the same exhausted provider.

### 3. Retry Budget & Same-SHA Anti-Loop Governance
- **Retry Budget:** 1 normal attempt + 1 corrective retry before root-cause classification.
- **Same-SHA Anti-Loop:** If `current SHA == previous SHA` AND same failure reason AND no new evidence:
  - Prohibit full-provider re-invocation.
  - Emit event `SAME_SHA_RETRY_SUPPRESSED`.
  - Trigger alternative action: lightweight reconciliation, platform recovery, or human gate.

### 4. Lightweight Reconciliation Service (`LightweightReconciliationService`)
- In-process reconciliation for `tasks.md` checkboxes, evidence diagnostics, and candidate manifest integrity.
- Detects when material code is changed, checks pass, and only task/evidence synchronization remains.
- Reconciles state deterministically in milliseconds without spawning LLM agents.

### 5. Reviewer Independence Enforcement (`AuthorshipService`)
- Builds complete material authorship set (`material_candidate_authors`) for each frozen candidate SHA.
- Computes `eligible_reviewers = configured_reviewers - material_candidate_authors`.
- If an assigned reviewer is in `material_candidate_authors`, reject with `REVIEWER_INDEPENDENCE_UNAVAILABLE`.
- Stops pipeline safely; prohibits `READY_TO_MERGE` from an ineligible reviewer.

### 6. Canonical `CHECKS_FAILED` Remediation Routing
- Failed checks classify failure into code/test fix (Codex), platform recovery (PLATFORM_RECOVERY), or bookkeeping (Lightweight).
- Increments candidate generation, creates next remediation attempt, and re-executes checks cleanly.

### 7. PostgreSQL Efficiency Telemetry & UI Projection
- Table: `provider_efficiency_metrics` storing per-change and per-run metrics.
- Read models accessible via `/api/v1/telemetry/efficiency/{project_id}/{change_name}`.
- Textual TUI and PWA surfaces render provider utilization, productive/no-progress ratios, same-SHA retries, and cycle times.
