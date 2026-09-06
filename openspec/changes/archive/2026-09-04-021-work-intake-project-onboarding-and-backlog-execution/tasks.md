# Tasks: 021 Work Intake, Project Onboarding, and Backlog Execution

## 021.1 Project Onboarding
- [x] Create Alembic migration `019_work_intake_and_backlog_items.py` with project onboarding columns and `backlog_items` table.
- [x] Implement domain and ORM models for `Project` enhancements and `BacklogItem`.
- [x] Implement `BacklogItemRepositoryInterface` and `SQLAlchemyBacklogItemRepository`.
- [x] Implement `ProjectOnboardingService` with repository identity validation, auto-discovery, conflict detection, and fail-closed checks.

## 021.2 Context & Backlog Discovery
- [x] Implement `ContextDiscoveryService` to scan README, docs, ROADMAP.md, BACKLOG.md, and OpenSpec changes.
- [x] Classify findings into Discovered Facts, Inferred Structure, and Missing Required Context.
- [x] Parse roadmap milestones and backlog items into normalized `BacklogItem` records.
- [x] Implement non-destructive reconciliation preserving manual edits and operator priority overrides.

## 021.3 Work Item Intake
- [x] Implement `IntakeService` supporting work item creation, update, question answering, and deletion.
- [x] Implement REST API endpoints for project context, discovery, and backlog management in `src/minime/api/app.py`.
- [x] Enforce authenticated operator authorization and audit events for all intake actions.

## 021.4 Canonical Artifact Generation
- [x] Implement `OpenSpecGenerator` for deterministic authoring of proposal, design, specs, and tasks.
- [x] Enhance `GitHubAdapter` with `create_issue` and `add_issue_to_project` with duplicate prevention.
- [x] Integrate artifact preparation pipeline in `IntakeService.prepare_work_item()`.
- [x] Implement `NEEDS_HUMAN` transition with explicit product questions for ambiguous or incomplete work items.

## 021.5 Readiness & Admission
- [x] Connect `ReadinessService` Definition of Ready checks to `BacklogItem` state.
- [x] Implement `start_work_item()` in `IntakeService` with duplicate start suppression and scheduler queue admission.
- [x] Verify integration with `SchedulerService` and `OrchestrationCoordinator`.

## 021.6 PWA Presentation & Proving
- [x] Update `index.html`, `dashboard.js`, and `dashboard.css` with Projects view, Backlog master/detail view, DoR checklist, and `NEEDS_HUMAN` resolution UI.
- [x] Verify desktop, tablet, and mobile responsiveness.
- [x] Implement automated test suite covering onboarding, context discovery, intake, artifact generation, DoR, admission, and PWA integration.
- [x] Execute end-to-end proving demonstrating work intake and execution with 0 human prompts to Antigravity.
