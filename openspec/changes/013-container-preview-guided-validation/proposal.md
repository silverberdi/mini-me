# Proposal: Container Preview & Guided UI Validation

## Why

mini me autonomously executes software-delivery cycles and provides real-time visibility through an operations dashboard. However, for UI-affecting changes, code-level checks and LLM reviews alone cannot provide sufficient visual certainty. Operators need trustworthy, candidate-bound preview environments and structured validation scenarios to verify user-facing behavior.

Crucially, human approval must be verifiable evidence bound to the exact candidate tuple `(head_sha, base_sha, image_digest)`. A validation for an older candidate generation or different image must never authorize a newer candidate. 013 introduces isolated container preview lifecycle management, deterministic image digest authority, guided validation scenarios, stale validation invalidation, and seamless operations dashboard integration.

## What Changes

This change delivers:

- **Preview Runtime Abstraction (`ContainerPreviewService`)**:
  - Container build from frozen candidate worktree capturing authoritative image digest directly from Docker.
  - Resource isolation with safe dynamic port allocation and deterministic naming (`minime-preview-<project>-<change>-gen<gen>`).
  - Strict database safety: preview containers are isolated and forbidden from accessing the canonical `minime` database.
  - Lifecycle state machine: `REQUESTED -> BUILDING -> STARTING -> PROBING -> READY` (or `FAILED`/`TERMINATED`).
  - Active HTTP health probing with bounded timeout and retries.
  - Idempotent teardown and safe restart/orphan recovery restricted strictly to mini me-owned preview containers.
- **Durable Persistence & Domain Model (`PreviewSession`, `ValidationRun`, `ValidationScenario`)**:
  - PostgreSQL schema and Alembic migration adding `preview_sessions` and `validation_runs` tables.
  - Entity models tracking preview lifecycle, container IDs, endpoints, image digests, scenario results, and operator verdicts.
- **Candidate Validation Authority & Delivery Gate Integration**:
  - Authoritative validation requirement derived from explicit OpenSpec metadata (`surface: ui` or `required_for_ui_changes: true`).
  - Candidate authority binding strictly to `(head_sha, base_sha, image_digest)`.
  - Stale validation invalidation: mutations in head SHA, base SHA, or image digest render prior validations non-authorizing while preserving them as historical evidence.
  - Orchestration pipeline integration: UI-affecting changes require a valid, non-stale validation `PASS` before advancing to `PR_PREPARED` / `READY_FOR_HUMAN_MERGE`.
- **Guided Validation Scenarios & Dashboard UI**:
  - Scenarios derived from OpenSpec acceptance criteria with ordered steps and expected outcomes.
  - REST API endpoints for preview lifecycle, scenarios, and validation submission/retrieval.
  - Dashboard UI extension: preview status card, candidate identity inspector, interactive scenario runner, stale validation warnings, and PASS/FAIL submission.
- **Automated Browser Assistance**:
  - Automated route/DOM health checks clearly distinguished from authoritative human validation.

## Capabilities

### New Capabilities
- `container-preview-runtime`: Automated build, start, probe, inspect, stop, and teardown of candidate-bound container previews with image digest authority and restart reconciliation.
- `candidate-validation-authority`: Candidate binding to `(head_sha, base_sha, image_digest)`, stale validation invalidation, and orchestration pipeline validation gating.
- `guided-validation-workflow`: Scenario progression, PASS/FAIL result recording, and dashboard UI integration for interactive operator validation.

### Modified Capabilities
- `execution-operations-dashboard`: Extended with preview and validation UI panels, candidate identity inspection, and scenario execution controls.
- `autonomous-change-orchestration`: Pipeline gate integration requiring valid candidate validation for UI changes before PR preparation.

## Non-Goals (Scope Boundaries)
- Implementing the 014 TUI Operator Console or 017 PWA Control Center.
- Implementing the 015 Operator Actions / Control Plane (e.g. arbitrary mutations or agent reassignment).
- Implementing 016 Autonomous Queue & Work Selection.
- Kubernetes or multi-node container cluster orchestration.
- Modifying canonical production databases or deploying production artifacts.

## Impact
- `src/minime/domain/`: Added `PreviewStatus`, `ValidationVerdict` enums and `PreviewSession`, `ValidationRun`, `ValidationScenario` models.
- `src/minime/db/`: Added SQLAlchemy models and Alembic migration for preview sessions and validation runs.
- `src/minime/services/`: Added `container_preview_service.py`, `validation_authority_service.py`, and updated `orchestration_service.py` and `dashboard_service.py`.
- `src/minime/api/`: Added preview and validation REST API endpoints.
- `src/minime/static/`: Extended HTML, CSS, and JS with guided validation interface.
- `tests/`: Comprehensive unit, integration, stale validation, and container tests.
