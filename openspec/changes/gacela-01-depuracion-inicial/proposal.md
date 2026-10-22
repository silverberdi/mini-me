## Why

La implementación actual conserva una arquitectura heredada que genera y fusiona artefactos OpenSpec por Python, planifica trabajo mediante una cola y puntuación propias y persiste estado que replica responsabilidades de GitHub u OpenSpec. Eso contradice el contrato rector 1.2 y hace que mini me sea difícil de operar y evolucionar. F1 reduce esa superficie sin pretender entregar todavía el nuevo ciclo de F3.

## What Changes

- Retirar la generación determinista de `proposal.md`, `design.md`, `specs` y `tasks`, incluida su activación desde intake, y las implementaciones Python que fusionan o archivan semánticamente OpenSpec.
- Retirar las rutas de ejecución, verificación, recuperación, configuración, pruebas y dependencias que solo existen para esas emulaciones; los workflows nativos quedan fuera de la responsabilidad semántica del daemon.
- Retirar de forma segura la cola local, scoring, clasificación y scheduler heredados cuando su responsabilidad duplique el proveedor de tickets o no tenga una función mínima vigente. Las operaciones afectadas deben rechazar explícitamente la solicitud hasta que F2/F3 las sustituyan; no pueden aparentar éxito ni reactivar trabajo autónomo.
- Reducir los modelos, repositorios y tablas PostgreSQL demostrablemente exclusivos de las rutas retiradas mediante una migración Alembic nueva, reversible y protegida por inventario/backup. Se conservarán autenticación, configuración útil de proyectos, bindings Git/GitHub, worktrees, secretos, autorizaciones y los checkpoints/evidencias mínimos que aún tengan consumidores legítimos.
- Reconciliar los Changes y specs históricos como evidencia no ejecutable: inventariar su estado y conflictos con el contrato, sin aplicar, archivar, borrar ni continuar ninguno automáticamente.

## Capabilities

### New Capabilities

- `native-openspec-boundary-retirement`: elimina las rutas que sustituyen la semántica de workflows oficiales OpenSpec y deja las operaciones no reconstruidas explícitamente fuera de servicio.
- `legacy-admission-and-state-retirement`: elimina la cola, selección, clasificación y estado PostgreSQL heredados que no son necesarios para la continuidad mínima, con migración conservadora y rollback.
- `legacy-surface-reconciliation`: reconcilia API, CLI, UI, pruebas y artefactos históricos para que no expongan ni documenten capacidades retiradas o futuras como activas.

### Modified Capabilities

- Ninguna. Las especificaciones históricas bajo `openspec/specs/` se preservan sin reescritura como evidencia; cuando contradicen el contrato rector 1.2 no son autoridad de producto ni de ejecución para F1.

## Impact

- Afecta `openspec_generator`, `openspec_sync`, `post_merge_service`, gates/lifecycle, intake/readiness/discovery/scheduler, pipeline/orchestration y sus consumidores de API, CLI, TUI/PWA y pruebas.
- Afecta modelos, interfaces, repositorios y migraciones Alembic relacionados con backlog local, cola, decisiones de scheduler, clasificación, y registros exclusivos de flujos heredados; el conjunto final se decide solo tras el Removal Ledger y el análisis de datos reales.
- Mantiene FastAPI, autenticación, registros de proyecto aprovechables, integraciones Git/GitHub, aislamiento de worktrees, la integración oficial de lectura/validación estructural de OpenSpec y los controles de secretos/autorización/costo. No habilita scheduler, no ejecuta agentes ni introduce servicios, APIs, frameworks o infraestructura nuevos.
