---
name: openspec-quality-hooks
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
   - The CLI obtains changed files and candidate blobs directly from Git. JSON review files and provenance labels are not authenticated evidence. Since durable reviewer records do not currently record specialty-level coverage, POST-APPLY is `BLOCKED` until that existing authority can prove reviewer identity, independence, candidate binding, and required specialties.
   - Scans diff for regression patterns (including PR #139 auth failure swallowing and secret leakage).
   - Execution: `python -m minime.quality_hooks.cli evaluate-post-apply --change "<id>" --base-sha "<base>" --candidate-sha "<cand>" --implementer-model "<model>"` (a review JSON file is not authority and cannot produce `PASS`).

3. **`VERIFY` (Quality & Acceptance Gate)**
   - Eliminates assumed PASS results. Tests, linters, and schemas are never assumed successful by default.
   - `--run-checks` verifies a clean worktree including untracked files, exports the exact candidate Git tree, and executes tests, Ruff, JSON Schema meta-validation, and strict OpenSpec validation there. Caller-supplied evidence files are never authority. Missing tools or inability to prove the candidate tree = `BLOCKED`.
   - Requires zero unresolved `CRITICAL` or `HIGH` findings. Any unresolved `CRITICAL` or `HIGH` finding = `FAIL`.
   - Returns explicit verdict: `PASS`, `FAIL`, or `BLOCKED`.
   - Execution: `python -m minime.quality_hooks.cli evaluate-verify --change "<id>" --base-sha "<base>" --candidate-sha "<cand>" --run-checks`

4. **`ARCHIVE` (Delivery Integrity)**
   - Validates Definition of Done (DoD) compliance.
   - Queries GitHub directly for the PR merge identity and a human approval bound to the exact head SHA; local JSON claims are not accepted.
   - The gate remains `BLOCKED` because no canonical aggregate Definition-of-Done record is currently connected. Do not describe a `PASS` or full closure until that evidence exists.
   - Execution: `python -m minime.quality_hooks.cli evaluate-archive --change "<id>" --base-sha "<base>" --candidate-sha "<cand>" --pull-request-number <number> --target-branch main`

Executable controls are the Git worktree/tree checks, test/lint/schema commands, GitHub PR lookup, and authenticated GitHub review lookup. Workflow and skill text is guidance only and never itself proves a gate.
