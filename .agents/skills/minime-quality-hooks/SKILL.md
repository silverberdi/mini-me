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
   - Dynamically selects required review specialties based on changed files and diff content:
     - `security_auth` (Security & Authorization)
     - `data_migrations` (Data & Migrations)
     - `reliability_recovery` (Reliability & Recovery)
     - `tests_coverage` (Tests & Functional Coverage)
     - `operational_delivery` (Operational Delivery)
     - `general_architecture` (General Architecture & Scope)
   - Enforces Reviewer Independence: the implementer and reviewer must be complementary distinct roles, and same model identity self-review is forbidden.
   - Scans diff for regression patterns (including PR #139 auth failure swallowing and secret leakage).
   - Execution: `python -m minime.quality_hooks.cli evaluate-post-apply --change "<id>" --base-sha "<base>" --candidate-sha "<cand>" --implementer-model "<model>" --reviewer-model "<model>"`

3. **`VERIFY` (Quality & Acceptance Gate)**
   - Requires concrete deterministic evidence (test results, lint results, schema checks). Missing evidence = `BLOCKED`.
   - Requires zero unresolved `CRITICAL` or `HIGH` findings. Any unresolved `CRITICAL` or `HIGH` finding = `FAIL`.
   - Returns explicit verdict: `PASS`, `FAIL`, or `BLOCKED`.
   - Execution: `python -m minime.quality_hooks.cli evaluate-verify --change "<id>" --base-sha "<base>" --candidate-sha "<cand>"`

4. **`ARCHIVE` (Delivery Integrity)**
   - Validates Definition of Done (DoD) compliance.
   - Requires mandatory human merge evidence (no autonomous merge in MVP).
   - Requires recorded human approval and candidate SHA alignment.
   - Execution: `python -m minime.quality_hooks.cli evaluate-archive --change "<id>" --base-sha "<base>" --candidate-sha "<cand>" --merged-by-human`
