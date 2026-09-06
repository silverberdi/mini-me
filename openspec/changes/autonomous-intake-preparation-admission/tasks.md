# Tasks: Autonomous Intake Preparation & Admission Policy

## Phase 1: Project Admission Policy Configuration & Schema
- [x] Extend `Project` model and repository with `auto_prepare`, `auto_admit`, and `max_concurrent_jobs` (defaults: `True`, `True`, `1`)
- [x] Add project policy validation in `ProjectService` and API project endpoints

## Phase 2: Autonomous Intake Preparation Pipeline
- [x] Integrate automatic `prepare_work_item()` invocation into `IntakeService.create_work_item()` when `auto_prepare = True`
- [x] Ensure automatic `prepare_work_item()` execution in `IntakeService.answer_human_question()`
- [x] Validate zero manual "Prepare Artifacts" clicks required on valid work item creation

## Phase 3: Autonomous Admission & Backlog Selection in Scheduler
- [x] Implement deterministic backlog ranking (`select_next_admissible_work_item`) in `SchedulerService` / `IntakeService`
- [x] Implement autonomous admission loop in `SchedulerService.tick()` bounded by `max_concurrent_jobs`
- [x] Enforce primary provider availability check before auto-admission (prevent OpenRouter from starting new work)
- [x] Auto-admit waiting `READY` items immediately upon primary provider recovery probe success
- [x] Release concurrency slot upon terminal closure (`COMPLETED` / `CANCELLED`) and immediately evaluate next eligible item

## Phase 4: UI & Observability
- [x] Expose admission policy settings, admission eligibility, and waiting reasons in PWA Backlog & Intake view
- [x] Expose policy and admission status in TUI
- [x] Persist structured audit events for automatic preparation, DoR transitions, and admission decisions

## Phase 5: Verification & Acceptance Proving
- [x] Unit test coverage for auto-preparation, DoR transitions, provider waiting, and ranking
- [x] Integration test for auto-admission and sequential execution with concurrency = 1
- [x] End-to-end verification across PostgreSQL, PWA API, TUI, and Scheduler
