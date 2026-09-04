# Specification: Work Intake, Project Onboarding, and Backlog Execution

## Requirements

### REQ-021.1: Project Onboarding & Repository Binding
The system MUST allow an authorized operator to register and bind a project/repository. The system MUST automatically probe and validate repository accessibility, discover base branch and OpenSpec configuration, detect conflicting bindings, fail closed on mismatch, and assign an onboarding status (`UNBOUND`, `BINDING`, `CONTEXT_INCOMPLETE`, `READY_FOR_WORK`, `BLOCKED`).

#### Scenario: Successful project onboarding with auto-discovery
- **GIVEN** a valid Git repository with standard context files (e.g. `README.md`, `ROADMAP.md`),
- **WHEN** the operator submits onboarding details with the repository identity,
- **THEN** the system verifies repository access, discovers default paths and branch, creates the `Project` entity in PostgreSQL, sets status to `READY_FOR_WORK`, and triggers initial context discovery.

#### Scenario: Onboarding fails closed on inaccessible repository
- **GIVEN** a non-existent or inaccessible repository identifier,
- **WHEN** the operator submits onboarding details,
- **THEN** the system rejects registration with an actionable error and does not persist invalid bindings.

### REQ-021.2: Context & Backlog Discovery
The system MUST inspect repository context sources and categorize findings into Discovered Facts, Inferred Structure, and Missing Required Context. The system MUST extract roadmap and backlog items into normalized `BacklogItem` records non-destructively.

#### Scenario: Discovery parses roadmap milestones without overwriting operator edits
- **GIVEN** a project with a markdown roadmap file containing milestones,
- **WHEN** context discovery is executed,
- **THEN** roadmap milestones are imported into `backlog_items` with priority, dependencies, and source pointers, while existing operator priority overrides are preserved.

### REQ-021.3: Work Item Intake & Management
The system MUST provide REST API and PWA interfaces to create, update, filter, sort, prioritize, and delete backlog work items. All mutations MUST require operator authorization and generate audit events.

#### Scenario: Operator creates and prioritizes a new work item
- **GIVEN** an active registered project,
- **WHEN** the operator submits a new work item with title, description, and `CRITICAL` priority,
- **THEN** the system stores the item in PostgreSQL, records an audit event, and exposes the item in the backlog view.

### REQ-021.4: Canonical Artifact Generation & Ambiguity Governance
The system MUST generate or synchronize canonical artifacts (GitHub Issue, GitHub Project item, and OpenSpec change files) for a work item upon request. If the work item lacks essential acceptance criteria or contains blocking ambiguity, the system MUST NOT fabricate details and MUST transition the item to `NEEDS_HUMAN` with clear product questions.

#### Scenario: Underspecified work item transitions to NEEDS_HUMAN
- **GIVEN** a backlog item with an empty or vague description and no acceptance criteria,
- **WHEN** the operator requests artifact preparation,
- **THEN** the system sets status to `NEEDS_HUMAN`, records specific human questions, and blocks OpenSpec change creation until answered.

#### Scenario: Well-specified work item produces canonical artifacts
- **GIVEN** a well-specified backlog item with clear criteria,
- **WHEN** the operator requests artifact preparation,
- **THEN** the system generates/syncs the GitHub Issue, Project v2 item, and valid OpenSpec change files (`proposal.md`, `specs/.../spec.md`, `tasks.md`).

### REQ-021.5: Definition of Ready & Autonomous Admission
The system MUST automate Definition of Ready (DoR) evaluation across all 11 criteria. Once `READY`, the operator can start execution, admitting the item into `SchedulerService` and spawning an `OrchestrationRun` through the canonical SDLC lifecycle. Duplicate start requests MUST be suppressed.

#### Scenario: Operator starts READY work item and scheduler admits it
- **GIVEN** a backlog item that has satisfied all DoR criteria,
- **WHEN** the operator clicks "Start Work",
- **THEN** the system marks the item `ADMITTED`, creates an `OrchestrationRun`, launches the SDLC pipeline with the assigned implementer (Codex), and subsequent start requests return the active run without duplicate jobs.

### REQ-021.6: PWA Operator Experience
The PWA MUST provide full desktop, tablet, and mobile interfaces for Projects and Backlog management, including interactive DoR checklists, `NEEDS_HUMAN` inline resolution, and artifact links.
