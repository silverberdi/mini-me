# Self-Hosting Runtime Diagnostic Specification

## Purpose
Expose operational self-hosting readiness diagnostics in StatusService without introducing database schema dependencies or mutating operational state.

## ADDED Requirements

### Requirement: Self-Hosting Status Diagnostic
The `StatusService` SHALL provide a method `get_self_hosting_diagnostic()` and include a `self_hosting` dictionary in `get_system_status()` with runtime engine and queue capability facts.

#### Scenario: StatusService returns self-hosting diagnostics
- **GIVEN** an active `StatusService` backed by a persistence unit of work
- **WHEN** `service.get_system_status()` is called
- **THEN** the returned dictionary SHALL contain a `self_hosting` key
- **AND** `self_hosting["runtime_engine"]` SHALL equal `"mini-me-runtime"`
- **AND** `self_hosting["status"]` SHALL equal `"SELF_HOSTING_READY"`
- **AND** `self_hosting["autonomous_queue"]` SHALL be `True`.
