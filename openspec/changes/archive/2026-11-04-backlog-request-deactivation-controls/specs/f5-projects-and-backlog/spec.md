## MODIFIED Requirements

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
