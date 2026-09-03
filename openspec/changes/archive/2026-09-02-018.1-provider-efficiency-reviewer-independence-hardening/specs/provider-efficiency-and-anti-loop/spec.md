# spec: Provider Efficiency and Anti-Loop Governance

## Requirements

### Requirement 1: Deterministic Task Classification
The system SHALL deterministically classify each task/attempt into one of: `ROUTINE_IMPLEMENTATION`, `ORDINARY_REMEDIATION`, `TEST_FIX`, `BOOKKEEPING_RECONCILIATION`, `EVIDENCE_RECONCILIATION`, `ARCHITECTURE`, `UX_VISUAL_QA`, `PLATFORM_RECOVERY`, `SPECIALIZED`.
The classification SHALL be computed from observable signals (stage, failure reason, OpenSpec task status, diff, check results) and SHALL NOT depend on opaque LLM prompts.

#### Scenario: Routine feature implementation classification
- **GIVEN** a newly admitted READY change with incomplete code tasks
- **WHEN** task classification is evaluated for the initial attempt
- **THEN** task class MUST evaluate to `ROUTINE_IMPLEMENTATION`.

#### Scenario: Bookkeeping only classification
- **GIVEN** an active change where code is modified and all automated checks pass
- **AND** remaining incomplete tasks in `tasks.md` are documentation or evidence checkboxes
- **WHEN** task classification is evaluated
- **THEN** task class MUST evaluate to `BOOKKEEPING_RECONCILIATION`.

---

### Requirement 2: Canonical Provider Roles and Selection (Rules A, E, F, H)
The system SHALL select Codex as the default workhorse for `ROUTINE_IMPLEMENTATION`, `ORDINARY_REMEDIATION`, and `TEST_FIX`.
When Codex is available and the task class is routine, Antigravity SHALL NOT be eligible, and the decision reason MUST be recorded as `PREMIUM_PROVIDER_NOT_REQUIRED`.
Antigravity SHALL ONLY be selected when an explicit premium reason code is valid (`ARCHITECTURE_REQUIRED`, `UX_VISUAL_QA`, `PLATFORM_RECOVERY`, `CODEX_NON_CONVERGENCE`, `SPECIALIZED_REASON`).
For `CODEX_NON_CONVERGENCE`, the system SHALL require evidence of 1 initial Codex attempt + 1 corrective retry + root-cause classification before Antigravity can be assigned.

#### Scenario: Routine implementation selects Codex and excludes Antigravity
- **GIVEN** task class is `ROUTINE_IMPLEMENTATION` and Codex health is `AVAILABLE`
- **WHEN** provider selection evaluates eligibility
- **THEN** Codex MUST be selected as executor
- **AND** Antigravity MUST be marked ineligible with reason `PREMIUM_PROVIDER_NOT_REQUIRED`.

#### Scenario: Antigravity selection requires valid premium reason
- **GIVEN** a task requiring `PLATFORM_RECOVERY`
- **WHEN** provider selection evaluates eligibility for Antigravity
- **THEN** Antigravity selection MUST persist reason code `PLATFORM_RECOVERY`.

---

### Requirement 3: Retry Budget & Same-SHA Anti-Loop (Rules B & C)
The system SHALL grant an implementation provider at most 1 normal attempt plus 1 corrective retry before enforcing root-cause classification.
If an attempt produces an identical candidate SHA with the same failure reason and no new evidence, the system SHALL NOT invoke another full implementation provider.
The system SHALL emit event `SAME_SHA_RETRY_SUPPRESSED` and divert to lightweight reconciliation, root cause classification, or platform repair.

#### Scenario: Duplicate same-SHA retry suppressed
- **GIVEN** a failed attempt with candidate SHA `abc1234`
- **AND** a subsequent attempt produces identical SHA `abc1234` with the same failure reason and no new evidence
- **WHEN** continuation evaluation runs
- **THEN** further implementation retries MUST be suppressed
- **AND** event `SAME_SHA_RETRY_SUPPRESSED` MUST be persisted.

---

### Requirement 4: Lightweight Reconciliation (Rule D)
The system SHALL provide an in-process lightweight reconciliation service for bookkeeping and evidence synchronization.
When code changes are present and checks pass, the reconciler SHALL synchronize `tasks.md` checkboxes, evidence diagnostics, and candidate manifest integrity in-process without invoking external LLM providers.

#### Scenario: In-process tasks reconciliation
- **GIVEN** an active change with passing checks and matching code diffs
- **AND** `tasks.md` has unverified checkboxes for completed items
- **WHEN** lightweight reconciliation executes
- **THEN** `tasks.md` MUST be updated in-process
- **AND** zero external LLM tokens or agent processes SHALL be consumed.
