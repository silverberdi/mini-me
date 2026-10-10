# Specification: N01 — operational-blocker-visibility

## ADDED Requirements

### Requirement: Primary Capability
The system SHALL implement N01 — operational-blocker-visibility as described by the scenarios below.

#### Scenario 1: Bloqueos históricos se clasifican sin inventar causas.
- **GIVEN** the configured environment for `mini me`,
- **WHEN** the capability is invoked,
- **THEN** Bloqueos históricos se clasifican sin inventar causas..

#### Scenario 2: Un fallo de cuota no se presenta como pregunta humana.
- **GIVEN** the configured environment for `mini me`,
- **WHEN** the capability is invoked,
- **THEN** Un fallo de cuota no se presenta como pregunta humana..

#### Scenario 3: Un bloqueo sin evidencia suficiente se muestra como UNKNOWN.
- **GIVEN** the configured environment for `mini me`,
- **WHEN** the capability is invoked,
- **THEN** Un bloqueo sin evidencia suficiente se muestra como UNKNOWN..

#### Scenario 4: El operador puede consultar el motivo sin inspeccionar PostgreSQL.
- **GIVEN** the configured environment for `mini me`,
- **WHEN** the capability is invoked,
- **THEN** El operador puede consultar el motivo sin inspeccionar PostgreSQL..

#### Scenario 5: Pruebas deterministas sin regresiones de seguridad.
- **GIVEN** the configured environment for `mini me`,
- **WHEN** the capability is invoked,
- **THEN** Pruebas deterministas sin regresiones de seguridad..
