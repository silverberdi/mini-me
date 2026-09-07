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

### Adaptive AI Execution & Continuity Requirements (Planning Reconciliation)
Future capabilities `adaptive-provider-model-routing` and `autonomous-degraded-mode-work-continuity` must explicitly model the following concepts as distinct operational domains:
1. **Routine Provider Selection**: Baseline assignment governed by project-level configuration (e.g. Codex implementer / Antigravity reviewer).
2. **Bounded Premium Recovery**: Specialized single-attempt escalation (`PREMIUM_RECOVERY_NON_CONVERGENCE`) triggered only when material candidate progress exists and primary executor exhibits non-convergence under exhausted budgets.
3. **Drain Fallback**: Paid secondary provider fallback (OpenRouter) activated strictly during dual-primary exhaustion for in-flight changes, never for routine execution or new change admission.
4. **Executor Non-Convergence**: Algorithmic classification of repetitive malformed output, premature stops, failing checks, or stagnant streaks distinct from provider unavailability.
5. **Reviewer Independence**: Enforced structural separation guaranteeing that an implementer/recovery model identity never reviews its own candidate.
6. **Genuine Human Gates**: Reserving `NEEDS_HUMAN` strictly for true operator decisions (product ambiguity, secret provisioning, irreversible operations, merge approval, policy changes), replacing deterministic executor non-convergence transitions with machine-operable states (`WAITING_CAPACITY`, `EXECUTOR_RECOVERY_REQUIRED`).

### Execution Stall Watchdog & Qwen Second-Level Recovery Requirements (`shared-skill-execution-harness-framework` & `autonomous-degraded-mode-work-continuity`)

#### 1. Execution Stall Watchdog (`autonomous-degraded-mode-work-continuity`)
- **Deterministic Normal Path**: mini me continues using deterministic lifecycle and provider policies as the normal execution path. Do NOT invoke an LLM for routine scheduler or lifecycle decisions.
- **State-Aware Stall Detection**: Detects when a material execution has stopped making meaningful progress using state-specific signals:
  - No stage transition for longer than the state-specific threshold.
  - No new execution evidence for longer than threshold.
  - Repeated identical failure.
  - Same candidate SHA + same failure + no new evidence.
  - Provider available but job not progressing.
  - Retry/reassignment activity without convergence.
  - Run / Job / Backlog projection inconsistency.
  - Provider capacity recovered but waiting work did not resume.
  - Long-lived intermediate execution state with no legitimate wait reason.
- **Legitimate Wait Preservation**: Do NOT classify legitimate waits as stalls:
  - `WAITING_FOR_PROVIDER` / `WAITING_CAPACITY`: Not stalled while provider wait is still valid.
  - `READY_FOR_HUMAN_MERGE`: Not stalled; genuine human governance gate.
  - `NEEDS_HUMAN`: Not stalled when a genuine product/authority/secret decision is outstanding.
  - `IMPLEMENTING` with no activity: Potentially stalled after configured threshold.
  - `CHECKS_RUNNING`: Evaluated against checks-specific threshold.
- **Configurable Thresholds**: Thresholds must be configurable by execution state and task class rather than a single global timeout.

#### 2. Qwen Second-Level Recovery Diagnosis (`shared-skill-execution-harness-framework`)
- **Constrained Recovery Analyst**: When a stall is detected, mini me may invoke a local Qwen model as a constrained second-level recovery analyst. Qwen must NOT replace canonical policy.
- **Bounded Diagnostic Snapshot**: Qwen receives a bounded recovery snapshot containing only relevant evidence:
  - Run state, Job state, and Backlog state.
  - Current stage and last state transitions.
  - Recent failures and retry/reassignment counters.
  - Candidate SHA and latest execution evidence.
  - Provider availability/health and relevant policy constraints.
  - Current execution role and elapsed time since progress.
  - No entire repository dumps unless explicitly required by a later authorized diagnostic step.
- **Reusable Diagnostic Harness/Skill**: Provide a reusable skill and execution harness `execution-stall-diagnosis` producing structured output:
  - `stall_classification`: `PROVIDER_CAPACITY_WAIT`, `EXECUTOR_NON_CONVERGENCE`, `MALFORMED_EXECUTION_RESULT`, `CHECKS_STALLED`, `PLATFORM_PROCESS_FAILURE`, `STATE_RECONCILIATION_DEFECT`, `PROVIDER_RECOVERY_NOT_PROPAGATED`, `GENUINE_HUMAN_GATE`, or `UNKNOWN`.
  - `probable_root_cause`: Causal diagnostic explanation.
  - `material_progress`: Boolean indicating whether meaningful code/spec progress was achieved.
  - `recommended_action`: `CONTINUE_WAITING`, `RETRY_DETERMINISTIC_STEP`, `PREMIUM_RECOVERY`, `DRAIN_CONTINUATION`, `RECONCILE_STATE`, `RESTART_FAILED_PROCESS`, `ESCALATE_PROVIDER`, or `NEEDS_HUMAN`.
  - `recommended_execution_role`: Role recommendation for next step.
  - `human_required`: Boolean flag for true human intervention.
  - `confidence`: Calibrated float score.
  - `evidence_summary`: Concise summary of diagnostic evidence.
  - `policy_constraints_considered`: List of evaluated canonical constraints.

#### 3. Policy Authority & Recovery Flow
- **Authority Boundary**: Qwen recommends; canonical deterministic policy authorizes.
- **Strict Invariants**: A Qwen recommendation must NEVER directly bypass retry budgets, reassignment budgets, reviewer independence, provider-role restrictions, OpenRouter drain policy, security gates, human merge authorization, or destructive-action policy. If Qwen recommends an action forbidden by policy, the action must not execute.
- **Durable Persistence**: Persist diagnosis model, diagnosis skill/harness, structured recommendation, confidence score, policy validation result, accepted/rejected action, and eventual recovery outcome.
- **Recovery Lifecycle Flow**:
  `Normal deterministic execution` -> `no progress beyond state-specific threshold` -> `watchdog marks STALLED / recovery analysis required` -> `Qwen local diagnosis` -> `deterministic policy validation` -> `permitted autonomous recovery` -> `lifecycle resumes`.
- **Escalation Constraint**: Only escalate to `NEEDS_HUMAN` when the remaining blocker genuinely requires human intent, authority, secrets, irreversible-risk approval, or mandatory governance. "No currently usable executor" by itself is not automatically a human decision.

#### 4. Local Model Policy
- **Quota & Cost Protection**: Prefer local Qwen for this diagnostic role because it does not consume scarce frontier quota, the task is classification/recovery analysis rather than unrestricted coding, and the output is constrained and policy-validated.
- **Model Tiers**: Initially prefer `qwen2.5-coder:7b-instruct-q4_K_M` for ambiguous recovery analysis; evaluate `qwen2.5-coder:3b` later for simpler stall classifications.
- **Dynamic Routing**: Do not make this model mapping immutable; it must resolve dynamically via the provider/model capability registry and routing policy.

#### 5. Telemetry Requirements
- **Effectiveness Telemetry**: Extend effectiveness telemetry requirements to support:
  - `stall_count`
  - `stall_duration`
  - `stall_classification`
  - `qwen_recovery_diagnosis_count`
  - `diagnosis_confidence`
  - `policy_accept_rate`
  - `automatic_recovery_success`
  - `escalation_rate`
  - `false_positive_stall`
  - `human_required_after_recovery_analysis`
  - `mean_time_to_recovery`
- **Dashboard Observability**: These metrics should eventually appear in AI Operations / Model Performance.

#### 6. Success Criteria
- Normal lifecycle remains deterministic; no LLM is invoked for routine scheduler transitions.
- Genuine stalls are detected automatically; legitimate waits are not misclassified as stalls.
- Qwen can diagnose stalled executions locally without bypassing canonical policy.
- Permitted recovery occurs without human intervention, decreasing false `NEEDS_HUMAN` gates while keeping recovery behavior measurable.

Backlog items are planning units. OpenSpec `tasks.md` remains the implementation checklist for the active change; do not duplicate every task into GitHub Issues.

