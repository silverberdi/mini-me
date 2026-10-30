# f5-self-hosted-delivery Specification

## Purpose

Definir evidencia de aceptación específica para F5: consola responsive probada en navegador y ejecución auténtica del único Change por mini me hasta cierre documental y remoto.

## Requirements

### Requirement: F5 Browser and Human Acceptance Evidence
F5 SHALL have actual browser E2E evidence for desktop, tablet and mobile covering five routes, two primary destinations, accessible focus, themes, empty/stale/offline states, measured/no-data metrics, security refusals, genuine HUMAN_REQUIRED and disabled F7 controls. Human visual validation SHALL specify prerequisites, actions and expected outcomes and bind results to head/base SHA and image digest when present. Superseded validations SHALL NOT certify the current candidate. Mocked APIs SHALL NOT count as real integration evidence. Any future Angular migration SHALL additionally compare the Angular candidate with the legacy frontend for bundle, performance, memory, responsive, safe PWA/offline and unit/E2E browser behavior before legacy retirement.

#### Scenario: Accept a frozen UI candidate
- **WHEN** an actual browser operates against the candidate application and authorized isolated services
- **THEN** recorded commands, exit codes, screenshots and before/after effects prove the required behavior on all device classes, with independent review against the immutable SHA and explicit human visual results.

#### Scenario: Real human integration is missing
- **WHEN** only mocked human-action responses, auth-shell HTTP 200, disabled controls or author reports are available
- **THEN** genuine HUMAN_REQUIRED acceptance remains BLOCKED and neither test counts nor task checkboxes declare F5 complete.

#### Scenario: Angular parity evidence is incomplete
- **WHEN** a future Angular candidate lacks comparison evidence for a required behavior, device class, security boundary, performance dimension or safe offline behavior
- **THEN** the legacy frontend SHALL remain in place and the migration SHALL NOT be declared at parity or approved for retirement.

### Requirement: Authentic Self Execution of the Single F5 Change
mini me SHALL orchestrate Request #173 as gacela-05-ui-self-hosted through real agents and official Explore, Propose, Apply, Verify, appropriate independent review, PR1, native Sync/Archive from a fresh documentation branch, PR2 and remote closure. CLI/API bootstrap SHALL avoid dependency on the unfinished UI. Run/worktree/request/change/candidate identity, workflow invocations, results, measured usage or UNKNOWN, gate decisions and remote effects SHALL remain traceable. Manual executor prompt relays and scripts replacing agents or OpenSpec SHALL NOT qualify. This F8 planning Change SHALL NOT claim, initiate or substitute for that self-execution lifecycle.

#### Scenario: Demonstrate full self execution
- **WHEN** mini me completes the authorized F5 lifecycle
- **THEN** evidence binds actual invocations and artifacts to the same Request and Change, confirms PR1 merge under complexity policy, native Sync/Archive, PR2 merge before ticket closure and durable lock release, without automatically starting F6.

#### Scenario: Ambiguous attempt or missing authorization
- **WHEN** a checkpoint, dispatch, model capacity, candidate identity or human authorization is ambiguous or missing
- **THEN** mini me preserves the same Run/worktree and history, stops fail-closed without automatic manual retry, and records the block without interpreting UNKNOWN as zero measured usage.

### Requirement: Planning and Future Phase Boundaries
This planning workflow SHALL NOT implement code, resume a Run, enable scheduler, deploy, migrate, merge, close tickets or initiate additional model workflows. F5 acceptance SHALL NOT claim F7 operations or Angular F8. Existing historical authorization and runtime reports SHALL retain their time and provenance rather than be promoted to fresh verification or new authority. F8 SHALL remain a future, disabled phase until separately authorized by the operator through its own Change.

#### Scenario: Produce planning artifacts
- **WHEN** native Propose produces proposal, specs, design and tasks
- **THEN** artifacts and CLI validation are reported as planning evidence only, with unresolved material gates explicit and all implementation tasks uncompleted.

#### Scenario: Keep F8 disabled during planning
- **WHEN** this Change is continued while Issue #190 remains planned and labeled `disabled`
- **THEN** no Angular engineering, implementation PR, deployment, scheduler execution, spend or remote ticket closure is initiated, and F8 remains ordered after F7.
