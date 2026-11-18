## ADDED Requirements

### Requirement: Operational Status and Evidence Fidelity for the Control Center
The dashboard read models SHALL expose only facts available from canonical runtime authorities and preserve their source identity, candidate binding and freshness where applicable. They SHALL distinguish logical scheduler admission mode from scheduler service lifecycle observation; if service lifecycle is not authoritatively observable, they SHALL return an explicit unavailable/unknown value rather than infer it. Provider availability, capacity, latency, cost, usage, concurrency and completion metrics SHALL be shown only when backed by a corresponding current read-model field. Missing, stale, contradictory or unauthorized evidence SHALL remain `UNKNOWN`, unavailable, stale or forbidden as appropriate. Any additional projection SHALL be read-only, reuse existing persistence/services, and introduce no new operational source of truth.

#### Scenario: Project scheduler process and admission mode separately
Given the backend can read the fixed `minime-scheduler.service` unit through its existing unprivileged, read-only systemd observation access
When the dashboard overview is requested
Then the response SHALL report service active state, boot enablement and logical admission mode as separate fields with independent source timestamps
And the observation SHALL be limited to the known unit and SHALL perform no control operation.

#### Scenario: Scheduler observation is inaccessible, stale, or unsupported
Given the unit observation fails, exceeds its one-second read timeout, is older than 30 seconds, or returns an unrecognized active/unit-file state
When the dashboard overview is requested
Then service active state and/or boot enablement SHALL be `UNKNOWN` while the independently sourced logical admission mode remains unchanged
And API health or PostgreSQL health SHALL NOT imply that the scheduler service is running or enabled.

#### Scenario: Scheduler observer cannot control or select units
Given a browser caller requests scheduler status or supplies a unit identifier
When the backend produces the dashboard read model
Then it SHALL observe only the fixed `minime-scheduler.service` unit using read-only systemd manager properties
And SHALL NOT accept caller-selected units, invoke shell or `systemctl`, acquire additional privileges, or start, stop, enable, disable, reload or otherwise control a service.

#### Scenario: Project current provider and budget evidence
Given provider health, budget usage and model-capacity observations have different timestamps or availability
When overview or detail is projected
Then each displayed value SHALL retain its distinct source and observation/freshness
And an absent or expired quota/budget field SHALL NOT be represented as zero usage or available capacity.

#### Scenario: Preserve exact candidate and event identity
Given a dashboard query includes a project, change, Run, Job or candidate with persisted events/evidence
When its detail or timeline is projected
Then event identity and chronology SHALL be preserved
And review/check/preview evidence from another candidate SHALL NOT be joined as current evidence.

#### Scenario: Reject unauthenticated operational reads
Given authentication is enabled and a request has no valid session or an unauthorized operator identity
When the request targets an operational dashboard or mutation endpoint
Then the existing authentication middleware SHALL reject it
And the projection SHALL not leak operational data or secrets.
