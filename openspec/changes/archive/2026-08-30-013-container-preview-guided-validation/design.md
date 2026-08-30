# Design: Container Preview & Guided UI Validation

## Architectural Context

mini me coordinates autonomous implementation, review, audit, and PR creation. For changes marked as affecting UI or requiring visual human validation, the system requires a deterministic, candidate-bound preview environment.

```text
+-----------------------------------------------------------------------------------+
|                            mini me Daemon & Core                                  |
|                                                                                   |
|  +-----------------------+     +--------------------------+     +---------------+ |
|  |  OrchestrationService  | --> | ValidationAuthorityService| --> | Dashboard API | |
|  +-----------------------+     +--------------------------+     +---------------+ |
|             |                                |                          |         |
|             v                                v                          v         |
|  +-----------------------+     +--------------------------+     +---------------+ |
|  |ContainerPreviewService|     | PostgreSQL (Durable)     |     | Dashboard UI  | |
|  +-----------------------+     | - preview_sessions       |     | (Guided Valid)| |
|             |                  | - validation_runs        |     +---------------+ |
|             v                  +--------------------------+                       |
|  +-----------------------+                                                        |
|  | Local Docker Runtime  |                                                        |
|  | - Build (frozen SHA)  |                                                        |
|  | - Digest Inspection   |                                                        |
|  | - Port Allocation     |                                                        |
|  | - Health Probing      |                                                        |
|  | - Idempotent Teardown |                                                        |
|  +-----------------------+                                                        |
+-----------------------------------------------------------------------------------+
```

## Domain Models & Persistence

### 1. `PreviewSession` & `PreviewSessionModel`
- `id`: `str` (UUID or `prev_...`)
- `project_id`: `str` (FK to `projects.id`)
- `change_name`: `str`
- `run_id`: `str | None` (FK to `orchestration_runs.id`)
- `job_id`: `str | None` (FK to `jobs.id`)
- `candidate_generation`: `int`
- `head_sha`: `str` (frozen candidate commit SHA)
- `base_sha`: `str` (base branch commit SHA)
- `image_digest`: `str` (immutable Docker image digest, e.g. `sha256:...`)
- `status`: `PreviewStatus` (`REQUESTED`, `BUILDING`, `STARTING`, `PROBING`, `READY`, `FAILED`, `TERMINATED`)
- `container_id`: `str | None`
- `container_name`: `str | None` (deterministic: `minime-prev-<proj>-<change>-gen<gen>`)
- `allocated_port`: `int | None`
- `preview_url`: `str | None` (`http://127.0.0.1:<port>`)
- `failure_reason`: `str | None`
- `failure_code`: `str | None`
- `created_at`: `datetime` (UTC)
- `ready_at`: `datetime | None`
- `terminated_at`: `datetime | None`

### 2. `ValidationRun` & `ValidationRunModel`
- `id`: `str` (UUID or `val_...`)
- `preview_id`: `str | None` (FK to `preview_sessions.id`)
- `project_id`: `str` (FK to `projects.id`)
- `change_name`: `str`
- `run_id`: `str | None`
- `candidate_generation`: `int`
- `head_sha`: `str`
- `base_sha`: `str`
- `image_digest`: `str`
- `verdict`: `ValidationVerdict` (`PASS`, `FAIL`)
- `scenario_results`: `list[dict]` (per-scenario status and notes)
- `notes`: `str | None`
- `operator`: `str | None`
- `created_at`: `datetime` (UTC)

### 3. `ValidationScenario`
- `scenario_id`: `str`
- `title`: `str`
- `description`: `str`
- `ordered_steps`: `list[str]`
- `expected_result`: `str`
- `viewport`: `str | None` (e.g. `desktop`, `mobile`)
- `required`: `bool` (default True)

## State Machine & Lifecycle

### Preview State Machine:
```text
REQUESTED -> BUILDING -> STARTING -> PROBING -> READY
    |            |           |          |
    +------------+-----------+----------+-----> FAILED
                                                   |
READY / FAILED -----------------------------> TERMINATED
```

### Health Probing:
- Uses bounded HTTP requests against the container's allocated port.
- Max attempts and timeouts are strictly enforced (e.g. 30 attempts, 1s interval).
- Success marks status as `READY` with timestamp.
- Failure / timeout transitions to `FAILED` and records failure reason and code without exposing internal secrets.

## Candidate Validation Authority & Stale Invalidation

Candidate authorization strictly enforces the tuple identity:
$$\text{Authority}(C) = (\text{head\_sha}_C, \text{base\_sha}_C, \text{image\_digest}_C)$$

Rules:
1. **Authorizing Condition**: A candidate $C$ is authorized if and only if there exists a recorded `ValidationRun` $V$ such that:
   $$V.\text{verdict} = \text{PASS} \land V.\text{head\_sha} = C.\text{head\_sha} \land V.\text{base\_sha} = C.\text{base\_sha} \land V.\text{image\_digest} = C.\text{image\_digest}$$
2. **Stale Invalidation**: If the candidate progresses to a new generation or changes head SHA, base SHA, or image digest, any older $V$ is evaluated as `stale = True`.
3. **Preservation**: Historical validations are never deleted or mutated; they remain immutable audit evidence.
4. **Gate Gating**: For changes requiring UI validation, `OrchestrationService` blocks `PR_PREPARED` and human merge gate until an active, non-stale `PASS` validation exists.

## Runtime Isolation & Container Safety

1. **Port Allocation**: Dynamic selection of available ephemeral ports (e.g. 18000–19000 range or OS-assigned), tracking ownership in the database.
2. **Database Isolation**: Preview containers run with mock or disposable SQLite/isolated test environments. The production `minime` PostgreSQL database connection string is strictly disallowed and rejected if injected.
3. **Orphan & Restart Recovery**:
   - On daemon startup, `ContainerPreviewService` inspects Docker for containers with label `app=minime-preview`.
   - Any container matching an active `PreviewSession` in `READY` or `PROBING` is health-checked.
   - Any container for a terminated or missing session owned by mini me is gracefully stopped and removed.
   - Containers not bearing the `app=minime-preview` label or belonging to other applications are never modified.

## Dashboard UI & Guided Validation Experience

The operations dashboard (`/static/index.html`) is updated with:
- **Preview & Validation Card**: Displays preview lifecycle status, preview URL link, candidate SHA, base SHA, image digest, and candidate generation.
- **Scenario Stepper**: Lists all validation scenarios with step instructions and expected visual outcomes.
- **Verdict Actions**: Interactive "PASS" and "FAIL" controls allowing operator submission with optional notes.
- **Stale Alert Banner**: Clearly flags when a previously passed validation was invalidated by code/base drift.
- **Responsive Aesthetics**: Adheres to the established dark/light theme, high information density, and accessible indicator styling.
