# pwa-preview-and-operator-actions Specification

## Purpose
TBD - created by archiving change 017-pwa-control-center. Update Purpose after archive.

## Requirements

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
The system SHALL render and execute only actions backed by current authenticated backend authority for the exact project, Run, stage and candidate. HUMAN_REQUIRED SHALL be answered in Trabajo actual with literal question/options and human authorization where required. The UI SHALL retain the question while submission is pending, refused or uncertain; only confirmed durable acceptance and refreshed authority SHALL show resolution. Acceptance SHALL NOT imply continuation unless the backend confirms it. Legacy endpoints returning 410 SHALL NOT be treated as action discovery or revived by F5.

#### Scenario: Execute continue action via confirmation modal
- **WHEN** the current backend authority permits continuation of the exact paused Run and candidate and the operator selects that action
- **THEN** an accessible modal explains its actual effects; confirming submits once to the supported operation and refreshes authoritative state, with no optimistic transition and continuation shown only after backend confirmation; a retired Control Plane endpoint provides no authority.

#### Scenario: Authorized human decision
- **WHEN** the operator confirms an authorized answer to a genuine HUMAN_REQUIRED in Trabajo actual
- **THEN** the UI submits to its supported backend operation once, displays the actual result, refreshes authoritative state and shows continuation only when confirmed by backend gates.

#### Scenario: Refusal, expiry or uncertain response
- **WHEN** an action returns 401/403, a stale-candidate refusal, 410, conflict or a timeout
- **THEN** no successful resolution or optimistic stage transition appears, the request remains unresolved until verified, and the UI does not automatically repeat the mutation or use another action as a substitute.

#### Scenario: Authority is missing
- **WHEN** no supported operation can durably answer the request
- **THEN** the UI explains the block, preserves its context and offers no simulated answer; F5 acceptance remains blocked rather than treating a disabled control as real HUMAN_REQUIRED support.

### Requirement: Destructive Action Safety Guard
The system SHALL require an accessible explicit confirmation describing actual effects before any authorized destructive or consequential action. Confirmation SHALL NOT create backend authority, authorize exceptional cost or bypass gates. No client operation SHALL directly invoke Git, agents, CLI, system services or arbitrary document writes.

#### Scenario: Cancel run with confirmation guard
- **WHEN** the operator selects Cancel Run for a Run whose current backend authority permits cancellation
- **THEN** an accessible prominent warning describes the actual supported cancellation effects and requires explicit confirmation before any mutation; cancellation is shown only after backend confirmation, and an unsupported cancellation remains unavailable without claiming subprocess termination.

#### Scenario: Decline a consequential action
- **WHEN** the operator cancels its confirmation dialog
- **THEN** no mutation is sent and focus returns to the initiating control.

#### Scenario: Future control is disabled
- **WHEN** the operator inspects a future F7 control with no backend authority
- **THEN** its reason is accessible without opening a success confirmation or emitting a mutation.
