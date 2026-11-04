## ADDED Requirements

### Requirement: Immediate feedback for human gate responses
Trabajo actual SHALL provide immediate optimistic feedback when the operator submits a response to the current human gate. While the response is being submitted, it SHALL hide the answered question and show submission progress. After server acceptance, it SHALL show «Respuesta enviada, procesando…» while the coordinator continues. If the response is rejected or the request fails, the UI SHALL restore the same unresolved gate and show the error. The optimistic state SHALL NOT alter the durable Run projection or claim that execution has completed.

#### Scenario: Response is accepted
- **WHEN** the operator submits a valid response and the existing endpoint accepts it
- **THEN** the answered gate is hidden immediately, «Respuesta enviada, procesando…» is shown, and the UI waits for the authoritative run update

#### Scenario: Response fails
- **WHEN** the endpoint rejects the response or the request fails
- **THEN** the gate question and options are restored and the UI displays an error without claiming acceptance

#### Scenario: Coordinator publishes the updated run
- **WHEN** a later SSE update refreshes the Run after the accepted response
- **THEN** the optimistic acknowledgement is reconciled with the authoritative current gate or run state, including any newly raised gate
