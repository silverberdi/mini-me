# Proposal: Operator Actions Control Plane

## Why

mini me can now observe its complete autonomous delivery lifecycle across the execution operations dashboard, container previews, guided validation workflows, and the interactive TUI operator console. However, operating and intervening in the delivery lifecycle (resuming paused runs, retrying failed stages, reassigning executors under governance, resolving human gates, or cancelling execution safely) still lacks a governed, canonical mutation boundary.

Currently, operational mutations risk being implemented ad-hoc or duplicated across presentation layers (CLI, TUI, and future PWA). Presentation layers must never own business action logic, execute unvalidated database mutations, or bypass authority rules.

Stage 015 delivers the **Operator Actions Control Plane** as the single canonical mutation layer for mini me. All operator-driven operations are structured as governed, audited commands with explicit actor identity, target binding, optimistic concurrency validation, policy checks, idempotency, and durable audit records.

## What Changes

This change delivers:

- **Canonical Control Plane Service & Domain Models (`src/minime/services/control_plane_service.py`, `src/minime/domain/models.py`)**:
  - `OperatorActionRequest`: Typed request entity capturing `action_request_id`, `project_id`, `change_name`, `run_id`, `action_type`, `parameters`, `actor_identity`, `source_interface`, `expected_state`, and timestamp.
  - `OperatorActionResult`: Structured result capturing `action_request_id`, `action_type`, `status` (`ACCEPTED`, `REJECTED`, `COMPLETED`, `FAILED`, `BLOCKED`), canonical error code, summary, resulting run/stage state, and durable evidence reference.
  - `OperatorActionRecord`: Immutable PostgreSQL persistence model recording full mutation audit trails.
  - `ActionDescriptor`: Machine-readable metadata for action discovery (`action`, `display_name`, `description`, `enabled`, `disabled_reason`, `requires_confirmation`, `confirmation_prompt`, `risk_level`, `parameters_schema`).
- **Governed Mutation Pipeline & Core Actions**:
  - **CONTINUE / RESUME**: Resumes paused or checkpointed runs using canonical orchestration semantics.
  - **RETRY**: Reruns failed checks or transient provider failures within retry budgets without accidental executor switching.
  - **REASSIGN**: Governed executor handoff enforcing provider capacity, mixed-authorship rules, model independence, and anti-ping-pong limits.
  - **RESOLVE GATE**: Explicit gate-specific resolvers for `NEEDS_HUMAN` conditions (`PRESERVED_CANDIDATE_INTEGRATION_CONFLICT`, `UI_VALIDATION_REQUIRED`). Disallows generic force-resolution.
  - **CANCEL**: Safe, non-destructive cancellation of eligible active runs, preserving candidate history, audit evidence, and Git refs while releasing owned preview resources.
  - **RECOVERY & PREVIEW**: Surfaces safe container preview actions (`start_preview`, `teardown_preview`) and lock recovery through the same governed interface.
- **Optimistic Concurrency & Idempotency**:
  - Validates expected run stage/generation/candidate SHA before mutating state, rejecting stale operator requests with structured `STALE_OPERATOR_STATE`.
  - Re-executing identical `action_request_id` returns the persisted prior result without re-triggering side effects or duplicate transitions.
- **REST API Endpoints (`src/minime/api/app.py`)**:
  - `GET /api/v1/runs/{run_id}/actions`: Action discovery returning enabled/disabled actions with explanation.
  - `POST /api/v1/runs/{run_id}/actions/{action}`: Governed execution endpoint.
  - `GET /api/v1/runs/{run_id}/actions/history`: Audit trail of operator actions for a run.
- **TUI Console Integration (`src/minime/tui/`)**:
  - Contextual Actions panel and command palette (`a` keybinding / Action menu) on the Run Detail screen.
  - Confirmation modals for destructive/material actions (Cancel, Reassign, Remediate).
  - Immediate visual feedback, status toasts, and dynamic run refresh.
  - Action History widget displaying timestamped operator mutations.
  - Preserves narrow (<110 cols), normal (110-170 cols), and wide (>170 cols) responsive layouts.
- **CLI Integration (`src/minime/cli/main.py`)**:
  - Refactored CLI commands (`minime orchestrate ...` and new `minime action ...`) to execute via the Control Plane service.
- **Database Schema & Alembic Migration**:
  - Migration creating `operator_action_records` table and indexes. Single Alembic head preserved.

## Capabilities

### New Capabilities
- `operator-actions-control-plane`: Governed operational control plane providing action discovery, optimistic concurrency, idempotency, durable action audit trails, and execution of safe operator commands (`resume`, `retry`, `reassign`, `resolve_gate`, `cancel`, `preview`).

### Modified Capabilities
- `tui-operator-console`: Extended to query action discovery, render contextual action controls, prompt for confirmation, and display action audit history.

## Non-Goals (Scope Boundaries)
- Autonomous queue / work selection or automatic priority dispatching (deferred to 016).
- PWA Control Center web application (deferred to 017).
- Full end-to-end self-operating development loop (deferred to 018).
- Direct arbitrary database mutations or bypass / god-mode overrides.
- Force-merging pull requests or skipping review/audit requirements.

## Impact
- `src/minime/domain/`: Added action types, result statuses, request/result models, error codes.
- `src/minime/db/`: Added `OperatorActionRecordModel` and repository interfaces.
- `alembic/versions/`: Added Alembic migration `013_operator_actions_control_plane.py`.
- `src/minime/services/`: Added `ControlPlaneService`, integrated with `OrchestrationService`, `ContainerPreviewService`, and `ValidationAuthorityService`.
- `src/minime/api/app.py`: Added action discovery, execution, and history endpoints.
- `src/minime/cli/main.py`: Integrated CLI action commands behind the control plane.
- `src/minime/tui/`: Added action discovery/execution client methods, action triggers, confirmation dialogs, and action history widget.
- `docs/CANONICAL_DECISIONS.md`: Updated with Control Plane architectural boundaries.
- `docs/ROADMAP.md`: Marked 015 as active/delivered.
