# Container Preview Runtime Specification

## ADDED Requirements

### Requirement: Preview Eligibility Determination
The system SHALL determine whether a candidate requires container preview and visual validation based on explicit change metadata (`surface: ui`) or project deployment configuration (`required_for_ui_changes: true`).

#### Scenario: UI change requires preview
Given an OpenSpec change with `surface: ui` or project configured with `required_for_ui_changes: true`
When the change candidate is evaluated for delivery readiness
Then preview deployment and visual validation SHALL be marked as required.

#### Scenario: Non-UI change does not require preview
Given a backend-only change without `surface: ui` and project config `required_for_ui_changes: false`
When the change candidate is evaluated
Then preview deployment SHALL NOT be required and the change SHALL NOT be blocked by preview validation.

### Requirement: Container Image Build and Digest Authority
The system SHALL build an isolated container preview image from the exact frozen candidate worktree and SHALL record the immutable image digest reported by the container runtime.

#### Scenario: Successful image build
Given a frozen candidate worktree with valid `head_sha`
When the preview runtime builds the container image
Then the runtime SHALL tag the image and retrieve the immutable sha256 image digest from the container runtime
And the preview session SHALL persist `head_sha`, `base_sha`, and `image_digest`.

#### Scenario: Image build failure
Given a candidate worktree with build syntax or dependency errors
When the preview runtime attempts to build the image
Then the build SHALL fail
And the preview session SHALL transition to status `FAILED` with a sanitized failure reason.

### Requirement: Preview Startup and Health Probing
The system SHALL start the built preview container on an isolated, dynamically allocated port and actively probe health until reachable or timed out.

#### Scenario: Container starts and reaches readiness
Given a successfully built candidate image
When the preview runtime launches the container and executes HTTP health probes
And the health probe returns HTTP 200 within the timeout limit
Then the preview session SHALL transition from `STARTING` and `PROBING` to `READY`
And the preview session SHALL record `preview_url` and `ready_at` timestamp.

#### Scenario: Health probe timeout
Given a container that starts but hangs or fails internal initialization
When health probing exceeds the maximum timeout limit
Then the preview session SHALL transition to `FAILED` with failure code `HEALTH_PROBE_TIMEOUT`.

### Requirement: Resource Isolation and Database Safety
The system SHALL isolate container runtime resources and SHALL NOT expose or inject the canonical production database into preview containers.

#### Scenario: Database protection guard
Given a preview container launch request
When environment configuration is constructed
Then the canonical `minime` database URL SHALL NOT be provided
And if an unsafe database configuration is detected, startup SHALL be denied.

### Requirement: Idempotent Teardown and Restart Reconciliation
The system SHALL support idempotent stopping and removal of preview containers and SHALL reconcile active preview sessions upon daemon restart without affecting foreign containers.

#### Scenario: Preview session teardown
Given a running preview container for a completed or cancelled change
When teardown is requested
Then the container SHALL be stopped and removed, and the allocated port SHALL be released
And subsequent teardown calls for the same session SHALL succeed without error.

#### Scenario: Orphan recovery on restart
Given the daemon restarts after an abnormal termination
When preview reconciliation runs
Then any orphaned containers labeled with `app=minime-preview` that have no active session SHALL be removed
And foreign containers lacking the mini me preview label SHALL NOT be touched.
