# Tasks: Container Preview & Guided UI Validation

## Task List

- [ ] 1. Canonical Context & OpenSpec Specification
  - [x] 1.1 Update `docs/ROADMAP.md` and `docs/BACKLOG.md` with canonical stages 013 through 018 and explicit stage boundaries.
  - [x] 1.2 Update `docs/CANONICAL_DECISIONS.md` with roadmap sequencing and stale validation rules.
  - [ ] 1.3 Validate OpenSpec change structure with `openspec validate --all --strict`.

- [ ] 2. Domain Models, DB Schema & Alembic Migration
  - [ ] 2.1 Define `PreviewStatus` and `ValidationVerdict` in `src/minime/domain/enums.py`.
  - [ ] 2.2 Define `PreviewSession`, `ValidationRun`, and `ValidationScenario` models in `src/minime/domain/models.py`.
  - [ ] 2.3 Define `PreviewSessionModel` and `ValidationRunModel` SQLAlchemy models in `src/minime/db/models.py`.
  - [ ] 2.4 Add repository CRUD methods and unit-of-work mappings in `src/minime/db/repository.py`.
  - [ ] 2.5 Create Alembic migration for `preview_sessions` and `validation_runs` tables maintaining a single DAG head.

- [ ] 3. Container Preview Runtime Service
  - [ ] 3.1 Implement `ContainerPreviewService` in `src/minime/services/container_preview_service.py` with Docker CLI / SDK abstraction.
  - [ ] 3.2 Implement isolated candidate image build extracting real sha256 image digest.
  - [ ] 3.3 Implement dynamic port allocation, container startup, and HTTP health probing with bounded retries.
  - [ ] 3.4 Implement idempotent teardown and restart/orphan reconciliation scoped strictly to mini me-owned preview containers.
  - [ ] 3.5 Enforce database protection denying production DB URLs in preview containers.

- [ ] 4. Candidate Validation Authority & Pipeline Gate Integration
  - [ ] 4.1 Implement `ValidationAuthorityService` in `src/minime/services/validation_authority_service.py`.
  - [ ] 4.2 Implement candidate authority tuple matching `(head_sha, base_sha, image_digest)` and stale invalidation evaluation.
  - [ ] 4.3 Integrate UI validation gate into `OrchestrationService` blocking `PR_PREPARED` and merge gates until valid PASS validation exists.
  - [ ] 4.4 Ensure non-UI changes bypass preview gate without stalling.

- [ ] 5. Guided Validation Scenarios & REST API Endpoints
  - [ ] 5.1 Implement scenario parsing from OpenSpec acceptance criteria and metadata.
  - [ ] 5.2 Implement REST API routes for preview lifecycle (create, get, probe, teardown) in `src/minime/api/app.py`.
  - [ ] 5.3 Implement REST API routes for validation submission and validation history in `src/minime/api/app.py`.

- [ ] 6. Operations Dashboard Integration & Guided Validation UI
  - [ ] 6.1 Update `DashboardService` projections in `src/minime/services/dashboard_service.py` to include preview and validation state.
  - [ ] 6.2 Extend `src/minime/static/index.html` with preview status card, candidate authority inspector, and guided scenario stepper.
  - [ ] 6.3 Update `src/minime/static/css/dashboard.css` with responsive, accessible styles for preview cards and scenario controls.
  - [ ] 6.4 Update `src/minime/static/js/dashboard.js` with preview polling, scenario interaction, stale warning display, and PASS/FAIL submission.

- [ ] 7. Comprehensive Automated Tests
  - [ ] 7.1 Unit and domain tests for preview sessions, validation runs, and stale invalidation.
  - [ ] 7.2 Container preview runtime unit tests with mocked and isolated subprocesses.
  - [ ] 7.3 Pipeline gate integration tests verifying UI candidate blocking vs non-UI bypass.
  - [ ] 7.4 Dashboard API and security tests verifying secret redaction and state projections.
  - [ ] 7.5 Database safety tests confirming rejection of canonical `minime` DB in preview configs.

- [ ] 8. Real Container Acceptance & End-to-End Verification
  - [ ] 8.1 Execute real local container preview build, startup, health probe, and teardown test with Docker.
  - [ ] 8.2 Verify orphan cleanup leaves no dangling mini me preview containers.
  - [ ] 8.3 Run full test suite, Ruff lint, and OpenSpec strict validation.
