# PWA Preview and Operator Actions Specification

## ADDED Requirements

### Requirement: Container Preview Lifecycle and URL Launcher
The system SHALL integrate with the 013 Container Preview Service to display real-time preview lifecycle status (`BUILDING`, `PROBING`, `READY`, `FAILED`, `STOPPED`), container port mappings, direct launch links to the preview URL, and exact image digest bindings.

#### Scenario: Launch active container preview
Given an active run with a container preview in `READY` status at URL `http://127.0.0.1:8788`
When the operator views the preview panel
Then the system SHALL display the `READY` status badge, port mappings, and an enabled `Open Preview` button linking to the URL.

### Requirement: Guided UI Validation Execution Checklist
The system SHALL render guided validation scenarios defined for the change, allowing the operator to verify steps, input validation notes, and submit authoritative `PASS` or `FAIL` verdicts bound to candidate `(head_sha, base_sha, image_digest)`.

#### Scenario: Submit passing guided validation verdict
Given an active preview for candidate `sha_abc123`
When the operator completes all validation scenario steps, enters notes "All checks verified", and clicks `Submit PASS`
Then the system SHALL invoke the backend validation endpoint
And update the preview state with the recorded passing validation evidence.

#### Scenario: Stale validation invalidation on candidate mutation
Given an authoritative validation was recorded for candidate `sha_abc123`
When a subsequent attempt creates new candidate `sha_def456`
Then prior validation records SHALL be flagged with `STALE (Invalidated by newer candidate)`
And a fresh validation SHALL be required for `sha_def456`.

### Requirement: Contextual Operator Control Plane Actions
The system SHALL consume backend action discovery (`/api/v1/control-plane/actions/available`) to dynamically render allowed mutation actions (`continue`, `retry`, `reassign`, `resolve_gate`, `cancel`, `start_preview`, `stop_preview`), disabling ineligible actions with clear tooltip explanations.

#### Scenario: Execute continue action via confirmation modal
Given a paused run with available action `continue`
When the operator clicks `Continue`
Then an accessible confirmation modal SHALL open explaining the impact of the action
And upon clicking `Confirm`, the system SHALL send `POST /api/v1/control-plane/actions/execute`
And trigger immediate optimistic UI update followed by telemetry refresh.

### Requirement: Destructive Action Safety Guard
The system SHALL require explicit confirmation with prominent warning text before executing destructive actions such as `cancel` or `reassign`.

#### Scenario: Cancel run with confirmation guard
Given an active execution run
When the operator clicks `Cancel Run`
Then a high-visibility modal SHALL require explicit confirmation stating that running subprocesses will be terminated
And the run SHALL NOT be cancelled until confirmation is given.
