# f5-projects-and-backlog Specification

## Purpose

Presentar Proyectos y su Backlog remoto con contexto verificable, acciones existentes autorizadas y representación honesta de capacidades futuras, sin duplicar la fuente de tickets.

## Requirements

### Requirement: Project Configuration and Authorized Context
The system SHALL present the selected project's real F2 configuration, onboarding and administrative state, distinct ticket and Git/PR connections, configured roles/models, and an authorized document index with source links and available version/freshness. Existing F2 operations SHALL retain their backend permissions. Missing document editing SHALL expose reading/editor/diff/save/cancel affordances disabled with a clear F7 reason; it SHALL NOT permit arbitrary path writes.

#### Scenario: Inspect a configured project
- **WHEN** the operator selects a project
- **THEN** its detail displays actual configuration and separate connections, contextual documents and a Backlog link without exposing secrets or implying that configuration starts a Run.

#### Scenario: Document authority is absent
- **WHEN** a referenced document cannot be read or edited through existing authorized APIs
- **THEN** the UI shows the authorized link or unavailability and disables unsupported reading/editing operations with an explanation instead of fetching arbitrary repository paths or pretending to save.

### Requirement: Deferred Project Controls
The system SHALL visually locate the future unique global executor selection and Pausar proyecto controls, with deferred-pause semantics after Change, PR2 and remote closure, or immediately when idle. They SHALL remain disabled with Disponible en F7 without real authority. F2 ACTIVE/PAUSED SHALL remain administrative and SHALL NOT be used as deferred pause, executor selection or evidence of execution.

#### Scenario: Administrative paused project
- **WHEN** F2 reports PAUSED without deferred-pause authority
- **THEN** administrative state is labeled separately and neither Pausa pendiente nor an executor transition is invented.

### Requirement: Authoritative Remote Backlog
The system SHALL present the selected project's configured ticket source as authority, with Pendientes ordered by remote eligibility and FIFO creation time plus stable ID, and Terminados by descending actual close time. Request detail SHALL include available original body, acceptance, traceability and remote evidence links. Eligibility, active, blocked, disabled and completed facts SHALL NOT be inferred from a local queue or invented outcome. Missing remote coverage SHALL show unavailable data rather than an empty list asserted complete.

#### Scenario: Inspect remote order and detail
- **WHEN** the provider supplies pending and closed Requests
- **THEN** the two tabs display their authoritative order, eligibility and context, preserving stable identities and linking real work to Trabajo actual where available.

#### Scenario: Partial source or remote failure
- **WHEN** the existing API exposes only eligible open Requests, or the provider fails
- **THEN** the UI identifies the partial coverage, does not claim to show all pending or completed Requests, and does not build a PostgreSQL backlog or call a retired local backlog endpoint.

### Requirement: Future Request Form and Logical Management
The system SHALL include a visual Nuevo Request form with mandatory natural-language title, description and acceptance criteria, plus contextual Editar, Desactivar, Reactivar and Eliminar lógicamente controls. Without existing backend authority, creation, editing and logical deletion SHALL remain disabled with an explanation Disponible en F7; controls SHALL NOT fake success or require operator-authored Gherkin. Desactivar and Reactivar SHALL be available for not-started Requests in the Backlog through their existing authorized endpoints. Future normalization SHALL reference the existing F4 capability rather than recreate it.

#### Scenario: Inspect a new Request form
- **WHEN** the operator opens the visual form without creation authority
- **THEN** all three required fields and their labels are visible, submission is disabled with its reason, and no mutation or synthetic Request is created.

#### Scenario: Apply state restrictions honestly
- **WHEN** the operator inspects a not-admitted, admitted, finalized or logically deleted Request
- **THEN** edit and logical-delete rules remain disabled without backend authority; Desactivar and Reactivar are offered only for not-started Requests; admitted work allows changes exclusively through authorized HUMAN_REQUIRED; finalized work is immutable and logically deleted work preserves history outside operational FIFO; physical deletion is never offered.

#### Scenario: Inspect disabled management confirmations
- **WHEN** the operator inspects an unsupported contextual management action
- **THEN** its explanation and intended logical effect are readable, disabled Requests are described as excluded from FIFO, and no confirmation claims that any state changed.

#### Scenario: Deactivate or reactivate a not-started Request
- **WHEN** the operator deactivates an active or reactivates a disabled not-started Request in Backlog
- **THEN** the UI calls the corresponding existing endpoint, reports success only after its successful response, refreshes the authoritative Request list, and reflects the resulting state without changing backend behavior.

### Requirement: Backlog Request Logical State
The system SHALL distinguish active Requests from Requests classified as `DISABLED` by the existing remote Request source, and SHALL display a supplied reason when one is present in the available Request payload. It SHALL NOT invent a reason or equate active state with FIFO eligibility when other authoritative status information says otherwise. A disabled Request SHALL remain excluded from admission FIFO.

#### Scenario: Display active and disabled Request states
- **WHEN** the Backlog displays active and disabled Requests
- **THEN** it labels their logical states as active and disabled respectively, offers the matching Desactivar or Reactivar control for not-started Requests, and displays the provided reason only when the payload supplies one.

#### Scenario: Reflect the FIFO effect of deactivation
- **WHEN** a Request is successfully deactivated or reactivated
- **THEN** the refreshed authoritative Backlog reflects the disabled/active state, and the existing admission behavior excludes the disabled Request and considers a reactivated Request under the existing FIFO eligibility rules.

#### Scenario: Mutation is rejected for a Request that has started
- **WHEN** a Request starts or becomes immutable before a Backlog action is accepted
- **THEN** the existing endpoint remains authoritative, the UI does not report a successful state change, and it refreshes or presents the returned error without changing backend rules.
