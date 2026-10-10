# Proposal: N01 — operational-blocker-visibility

## Problem Statement
Exponer causas respaldadas por evidencia persistida. Distinguir HUMAN_DECISION, PROVIDER_CAPACITY, TECHNICAL_FAILURE, DEPENDENCY, READINESS y UNKNOWN.

## Proposed Change
Deliver the capabilities and requirements defined for `operational-blocker-visibility`.

## Acceptance Criteria
- Bloqueos históricos se clasifican sin inventar causas.
- Un fallo de cuota no se presenta como pregunta humana.
- Un bloqueo sin evidencia suficiente se muestra como UNKNOWN.
- El operador puede consultar el motivo sin inspeccionar PostgreSQL.
- Pruebas deterministas sin regresiones de seguridad.

## Non-Goals
- Opportunistic refactoring outside the defined acceptance criteria.
- Undocumented scope changes or speculative features.

## Capabilities
- `n01-operational-blocker-visibility`: N01 — operational-blocker-visibility
