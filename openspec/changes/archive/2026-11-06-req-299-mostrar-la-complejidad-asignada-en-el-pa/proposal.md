# Proposal

## Why

El panel de Trabajo actual ya muestra el stepper de fases, pero no hace visible la complejidad asignada durante VALIDATING ni la evidencia que explica su interpretación. Esto impide al operador entender por qué un cambio puede requerir revisión obligatoria de propuesta y código, aunque la evaluación ya esté disponible en el Run.

## What Changes

- Mostrar en el panel «Fases del Pipeline de Orquestación» la complejidad de `targetRun()?.stop_details?.complexity` cuando sea `high`, `moderate` o `low`.
- Mostrar `stop_details.complexity_evidence` cuando exista, sin recalcular ni reinterpretar la evaluación.
- Mostrar «Pendiente» cuando todavía no exista una evaluación, sin inventar un nivel.
- Hacer visible la implicación operativa de una complejidad alta: revisión obligatoria de propuesta y código, según los datos y estados ya expuestos por el Run.
- Mantener el cambio limitado al frontend; no modificar el backend, el contrato de `GET /api/v1/orchestration/runs` ni la lógica de evaluación.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `pwa-runs-and-pipeline-observability`: el stepper de Trabajo actual debe mostrar la complejidad asignada, su evidencia disponible y el estado pendiente sin inferencias, manteniendo la observabilidad de las revisiones derivada del Run.

## Impact

- Frontend Angular: plantilla y lógica del componente `frontend/src/app/features/trabajo-actual/trabajo-actual.component.ts`.
- Modelo frontend existente: reutilización de `stop_details` en `frontend/src/app/core/models.ts`; no se añade un contrato API ni una fuente de datos nueva.
- Pruebas frontend: cobertura de niveles `high`, `moderate`, `low`, ausencia de evaluación, evidencia y lectura desde `targetRun()`; build frontend como comprobación de integración.
- Backend, base de datos, migraciones, evaluación de complejidad y endpoint permanecen sin cambios.
