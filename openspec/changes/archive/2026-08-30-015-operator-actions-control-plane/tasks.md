# Tasks: Operator Actions Control Plane

- [x] 1. OpenSpec Contract and Domain Definition <!-- id: 1 -->
  - [x] 1.1 Author 015 OpenSpec change proposal, design, tasks, and specifications. <!-- id: 1.1 -->
  - [x] 1.2 Define domain enums (`OperatorActionType`, `OperatorActionStatus`, `OperatorActionErrorCode`) and Pydantic models (`OperatorActionRequest`, `OperatorActionResult`, `ActionDescriptor`). <!-- id: 1.2 -->
  - [x] 1.3 Validate OpenSpec change structure with `openspec validate --all --strict`. <!-- id: 1.3 -->

- [x] 2. PostgreSQL Persistence and Alembic Migration <!-- id: 2 -->
  - [x] 2.1 Define SQLAlchemy model `OperatorActionRecordModel` in `src/minime/db/models.py`. <!-- id: 2.1 -->
  - [x] 2.2 Create linear Alembic migration `013_operator_actions_control_plane.py` and verify single head. <!-- id: 2.2 -->
  - [x] 2.3 Implement `OperatorActionRepository` and integrate into `PostgresPersistenceUnitOfWork`. <!-- id: 2.3 -->

- [x] 3. Core Control Plane Service Implementation <!-- id: 3 -->
  - [x] 3.1 Implement `ControlPlaneService` with action discovery (`get_available_actions`). <!-- id: 3.1 -->
  - [x] 3.2 Implement optimistic concurrency checks (`validate_expected_state`). <!-- id: 3.2 -->
  - [x] 3.3 Implement idempotency protection on `action_request_id` returning persisted result. <!-- id: 3.3 -->
  - [x] 3.4 Implement action executors: `CONTINUE`/`RESUME`, `RETRY`, `REASSIGN`, `RESOLVE_GATE`, `CANCEL`, `START_PREVIEW`, `TEARDOWN_PREVIEW`, `RECOVER_LOCKS`. <!-- id: 3.4 -->
  - [x] 3.5 Implement cancellation safety preserving candidate/audit evidence and cleaning owned preview containers. <!-- id: 3.5 -->
  - [x] 3.6 Implement durable action record persistence with secret redaction. <!-- id: 3.6 -->

- [x] 4. FastAPI REST Endpoints Integration <!-- id: 4 -->
  - [x] 4.1 Implement `GET /api/v1/runs/{run_id}/actions` for action discovery. <!-- id: 4.1 -->
  - [x] 4.2 Implement `POST /api/v1/runs/{run_id}/actions/{action}` for governed action execution. <!-- id: 4.2 -->
  - [x] 4.3 Implement `GET /api/v1/runs/{run_id}/actions/history` for action audit trail. <!-- id: 4.3 -->

- [x] 5. CLI Refactoring and Alignment <!-- id: 5 -->
  - [x] 5.1 Update `minime orchestrate ...` subcommands to delegate mutations to `ControlPlaneService`. <!-- id: 5.1 -->
  - [x] 5.2 Add `minime action list` and `minime action execute` CLI commands. <!-- id: 5.2 -->

- [x] 6. TUI Operator Console Integration <!-- id: 6 -->
  - [x] 6.1 Extend `TuiQueryClient` with action discovery, execution, and history methods. <!-- id: 6.1 -->
  - [x] 6.2 Add contextual Actions widget / Action Bar to Run Detail screen. <!-- id: 6.2 -->
  - [x] 6.3 Implement confirmation modal dialogue for material/destructive actions (Cancel, Reassign, Remediate). <!-- id: 6.3 -->
  - [x] 6.4 Implement Action History widget displaying audit records. <!-- id: 6.4 -->
  - [x] 6.5 Ensure keyboard shortcuts (`a` for actions) and verify narrow, normal, and wide layout responsiveness. <!-- id: 6.5 -->

- [x] 7. Comprehensive Acceptance and Safety Verification <!-- id: 7 -->
  - [x] 7.1 Unit and integration tests for Action Matrix (valid vs invalid states). <!-- id: 7.1 -->
  - [x] 7.2 Stale-state rejection tests and duplicate request idempotency tests. <!-- id: 7.2 -->
  - [x] 7.3 Cancellation safety and preview teardown tests. <!-- id: 7.3 -->
  - [x] 7.4 TUI pilot tests verifying action discovery, confirmation modal, and execution feedback. <!-- id: 7.4 -->
  - [x] 7.5 Real controlled action acceptance tests. <!-- id: 7.5 -->

- [x] 8. Full Baseline Checks, Review, Audit, and Closure <!-- id: 8 -->
  - [x] 8.1 Run full check suite: `pytest`, `ruff check .`, `git diff --check`, `openspec validate --all --strict`, `alembic heads`. <!-- id: 8.1 -->
  - [x] 8.2 Perform independent complementary review against OpenSpec contract. <!-- id: 8.2 -->
  - [x] 8.3 Perform DeepSeek Direct final audit against frozen candidate. <!-- id: 8.3 -->
  - [x] 8.4 Update canonical documentation (`docs/CANONICAL_DECISIONS.md`, `docs/ROADMAP.md`). <!-- id: 8.4 -->
  - [x] 8.5 Synchronize and archive OpenSpec change. <!-- id: 8.5 -->
