---
name: minime-quality-hooks
description: Enforce OpenSpec Lifecycle Quality Hooks V1 (PRE-APPLY, POST-APPLY, VERIFY, ARCHIVE) across agent workflows.
---
# OpenSpec Lifecycle Quality Hooks V1

This skill enforces model- and tool-agnostic quality gates associated with specific stages of the OpenSpec lifecycle.

## Stages & Quality Gates

1. **`PRE-APPLY` (Implementation Readiness)**
   - Validates presence and structure of OpenSpec change artifacts (`proposal.md`, `specs/`, `tasks.md`, `design.md`).
   - Verifies base SHA and candidate SHA formatting.
   - Enforces scope discipline (no out-of-scope files or future roadmap tasks).
   - Execution: `python -m minime.quality_hooks.cli evaluate-pre-apply --change "<id>" --base-sha "<base>" --candidate-sha "<cand>"`

2. **`POST-APPLY` (Expert Review & Dynamic Specialties)**
   - Obtains authoritative changed files and git diff directly from Git (`base_sha..candidate_sha`).
   - Dynamically selects required review specialties based on changed files and diff content:
     - `security_auth` (Security & Authorization)
     - `data_migrations` (Data & Migrations)
     - `reliability_recovery` (Reliability & Recovery)
     - `tests_coverage` (Tests & Functional Coverage)
     - `operational_delivery` (Operational Delivery)
     - `general_architecture` (General Architecture & Scope)
   - Enforces Reviewer Independence: the implementer and reviewer must be complementary distinct roles, and same model identity self-review is forbidden.
   - Requires authoritative review evidence (`--review-evidence-file`). Self-declared identities or declared specialties without evidence are strictly `BLOCKED`.
   - Scans diff for regression patterns (including PR #139 auth failure swallowing and secret leakage).
   - Execution: `python -m minime.quality_hooks.cli evaluate-post-apply --change "<id>" --base-sha "<base>" --candidate-sha "<cand>" --implementer-model "<model>" --review-evidence-file "<review.json>"`

3. **`VERIFY` (Quality & Acceptance Gate)**
   - Eliminates assumed PASS results. Tests, linters, and schemas are never assumed successful by default.
   - Requires concrete deterministic evidence bound strictly to the candidate SHA (`--evidence-file` or `--run-checks`). Missing evidence = `BLOCKED`.
   - Requires zero unresolved `CRITICAL` or `HIGH` findings. Any unresolved `CRITICAL` or `HIGH` finding = `FAIL`.
   - Returns explicit verdict: `PASS`, `FAIL`, or `BLOCKED`.
   - Execution: `python -m minime.quality_hooks.cli evaluate-verify --change "<id>" --base-sha "<base>" --candidate-sha "<cand>" --evidence-file "<evidence.json>"` (or `--run-checks`)

4. **`ARCHIVE` (Delivery Integrity)**
   - Validates Definition of Done (DoD) compliance.
   - Requires authoritative merge evidence bound to candidate SHA and confirmed human merge (`--merge-evidence-file`). Self-declared flags are not accepted.
   - Requires authoritative recorded human approval bound to candidate tuple (`--human-approval-file`).
   - Returns `BLOCKED` if authoritative evidence is absent.
   - Execution: `python -m minime.quality_hooks.cli evaluate-archive --change "<id>" --base-sha "<base>" --candidate-sha "<cand>" --merge-evidence-file "<merge.json>" --human-approval-file "<approval.json>"`
