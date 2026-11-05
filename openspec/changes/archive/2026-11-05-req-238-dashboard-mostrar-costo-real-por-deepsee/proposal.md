# Proposal

## Why

La gráfica del Dashboard que presenta “Tokens / Recursos IA consumidos” no representa de forma confiable el costo liquidado: su lectura actual puede apoyarse en datos de Run/tokens o en valores no verificables, mientras que el consumo facturado de DeepSeek Direct y OpenRouter ya pertenece al ledger durable de PostgreSQL. El operador necesita distinguir cuánto se liquidó por proveedor y modelo, y reconocer explícitamente cuándo no existe un costo verificable.

## What Changes

- Cambiar la fuente de datos de la visualización de costo del Dashboard para consultar únicamente entradas liquidadas y verificables de `budget_ledger`, conservando el timestamp y la identidad de proveedor/modelo.
- Mostrar costos reales en USD separados como mínimo entre DeepSeek Direct y OpenRouter, con precisión coherente con los importes durables y desglose por modelo cuando esté disponible.
- Representar la ausencia de costo verificable como un estado explícito de “sin datos”; no mostrar `0`, `CLI`, estimaciones ni atribuciones por defecto.
- Cubrir la representación de ambos proveedores con pruebas de UI y una ruta E2E real desde PostgreSQL/ledger hasta la gráfica.
- Retirar del recorrido de costo del Dashboard el consumo de `run.tokens` y cualquier valor sintético o fallback que pueda sustituir al ledger; conservar las rutas y datos históricos del ledger.

## Capabilities

### New Capabilities

### Modified Capabilities

- `execution-operations-dashboard`: el read model y la UI del Dashboard deben representar costo liquidado desde el ledger durable por proveedor/modelo, con serie temporal respaldada por timestamps y estado “sin datos” cuando no haya evidencia verificable.

## Impact

- Backend: `src/minime/services/dashboard_service.py`, la API de Dashboard en `src/minime/api/app.py` y los contratos/repositorios existentes para leer `budget_ledger`; se reutilizará la autoridad durable ya implementada por `budget_service` y sus migraciones PostgreSQL.
- Frontend: la vista Dashboard (`frontend/src/app/features/dashboard/dashboard.component.ts` y/o los assets estáticos equivalentes) dejará de presentar la serie de costo como tokens y mostrará proveedor, modelo, USD, precisión y estado sin datos.
- Pruebas: ampliar pruebas de Dashboard/UI, API y PostgreSQL para DeepSeek y OpenRouter, incluyendo ausencia de ledger, no atribución por defecto y el recorrido E2E observable.
- No se introduce una segunda fuente de verdad, una cola paralela, una migración de autoridad financiera ni despliegue productivo; los cambios de código quedan limitados a este Change.
