# Proposal

## Why

Las observaciones de Watchdog pueden quedar sin la clave de transición e identidad de evento que exige la detección de recurrencias, por lo que el primer diagnóstico no habilita los diagnósticos posteriores. Como consecuencia, `improvement_suggestion` permanece vacío y `/mejora-continua` no muestra propuestas aunque existan gates o intervenciones técnicas recurrentes; el Change corrige esa pérdida de persistencia y catalogación.

## What Changes

- Persistir cada diagnóstico Watchdog con su identidad de run, etapa, candidato y clave de transición/intervención disponible, sin depender de que exista un diagnóstico previo.
- Corregir la evaluación de recurrencia para que los diagnósticos posteriores encuentren el registro previo correcto sin romper la idempotencia de la persistencia.
- Asociar la sugerencia generada por el análisis semántico al diagnóstico persistido y conservar su estado inicial `pending`.
- Mantener la exposición autenticada de diagnósticos con sugerencia en `/api/v1/admin/watchdog/diagnoses`, incluyendo el registro pendiente que consume la vista `Mejora Continua`.
- Añadir o ajustar evidencia de integración y navegador para demostrar la invocación, persistencia, respuesta administrativa y visualización del registro pendiente; no crear Issues automáticamente.

## Capabilities

### New Capabilities

### Modified Capabilities

- `run-stall-watchdog`: garantizar la persistencia siempre ligada a la transición/intervención observada, la identidad del evento y la sugerencia de prevención cuando el análisis la produce, conservando la idempotencia y los límites de recuperación.
- `continuous-improvement-feed`: hacer visibles en el feed autenticado las sugerencias Watchdog realmente persistidas con estado `pending`, junto con su diagnóstico y evidencia de origen.

## Impact

- Backend: `WatchdogObservationService`, `PostgresWatchdogRepository`, el flujo de diagnóstico en `src/minime/cli/main.py` y los endpoints administrativos existentes.
- Persistencia: registros existentes de `watchdog_diagnoses` y su evidencia JSON; cualquier ajuste de esquema deberá ser conservador y compatible con PostgreSQL/Alembic.
- Frontend: consumo de `/api/v1/admin/watchdog/diagnoses` y visualización existente de `/mejora-continua`.
- Verificación: pruebas acotadas de backend/repositorio y una prueba E2E de navegador con datos persistidos y respuesta observable; no incluye despliegue productivo ni creación autónoma de tickets.
