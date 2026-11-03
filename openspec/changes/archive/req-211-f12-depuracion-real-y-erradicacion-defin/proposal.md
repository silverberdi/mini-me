# Proposal

## Why

La auditoría posterior a F6 encontró que el producto aún conserva la TUI, componentes de consola huérfanos, rutas HTTP 410, restos de interfaces web legacy, emulación de OpenSpec y pruebas/mocks orientados a código retirado. F12 elimina únicamente esas superficies cuando el censo estático y dinámico pruebe que no tienen consumidores legítimos, manteniendo la capacidad operativa real de mini me y reduciendo el coste de mantenimiento.

## What Changes

- Eliminar completamente `src/minime/tui/`, el comando `minime console`/`tui` y los grupos CLI muertos indicados por el Request #211; retirar dependencias huérfanas como `textual`.
- Eliminar la interfaz web previa a F8 que no pertenezca al build Angular activo y retirar rutas/decoradores 410 y sus servicios legacy sin consumidores.
- Retirar residuos de emulación semántica de OpenSpec, flujos huérfanos, modelos de dominio y métodos de Unit of Work exclusivamente legados, preservando la integración CLI nativa de OpenSpec y la coordinación operativa vigente.
- Retirar tablas, repositorios, configuración y migraciones nuevas únicamente cuando el inventario confirme que no tienen writers, readers, referencias durables ni obligación histórica; cualquier eliminación de PostgreSQL usará Alembic, respaldo y rollback comprobables.
- Eliminar tests de rutas, TUI y servicios retirados, reemplazando solo las protecciones necesarias por pruebas de contratos activos; los mocks no se presentarán como evidencia E2E.
- Mantener `NativeOrchestrationCoordinator`, `CliAgentRunner`, `WorktreeManager`, `GitHubAdapter`, adaptadores CLI de OpenCode/Codex/Antigravity, la API activa para la PWA Angular, OAuth Google, autorización de operadores y el build Angular.
- Verificar después del retiro los flujos operativos reales, la ausencia de entrypoints obsoletos y la suite retenida contra el SHA candidato; no desplegar, iniciar scheduler ni activar capacidades F7.

## Capabilities

### New Capabilities

- `f12-dead-code-retirement`: contrato observable para depurar superficies TUI/legacy/OpenSpec/tests/DB obsoletas, conservar capacidades activas y demostrar no-regresión tras el retiro.

### Modified Capabilities

- `f6-final-retirement`: amplía el inventario y la evidencia post-retiro para la depuración posterior a F6, sin borrar historia, candidatos, worktrees ni migraciones aplicadas.
- `legacy-surface-reconciliation`: las superficies retiradas sin consumidores se eliminan en vez de conservar respuestas 410 de transición; las superficies históricas con obligación legítima permanecen documentadas y protegidas.
- `native-openspec-boundary-retirement`: elimina restos de emulación y flujos locales huérfanos, conservando solo inspección estructural y handoff hacia workflows oficiales nativos.
- `tui-operator-console`: sustituye el contrato de provisión de la TUI por su retiro definitivo y la ausencia de imports, comandos y dependencias activas; preserva las rutas Angular `/`, `/dashboard`, `/trabajo`, `/trabajo-actual`, `/proyectos` y `/backlog`, con la ruta wildcard redirigida a `/dashboard`.
- `scheduler-tui-observability`: elimina la observabilidad TUI de scheduler/cola junto con sus entrypoints, sin reactivar scheduler ni transferir su responsabilidad a otra interfaz.

La frontera FastAPI preservada en esta delta incluye `/api/v1/projects` y sus rutas activas de configuración/onboarding/contexto y `/api/v1/projects/{project_id}/requests` y sus operaciones remotas, además de `/health`, `/status`, `/scheduler/status`, `/providers/health`, `/budget/usage`, `/projects/{project_id}/budget` y `/api/v1/auth/me`. Estas rutas se comprueban como consumidores activos antes y después del retiro; no se preservan las rutas 410 sin consumidor legítimo.

## Impact

- Código: `src/minime/tui/`, `src/minime/cli/main.py`, `src/minime/api/app.py`, servicios legacy/OpenSpec, modelos/repositorios y configuración relacionados.
- Frontend: `src/minime/static/`, conservando exclusivamente el build Angular en uso.
- Pruebas y dependencias: `tests/`, `pyproject.toml` y fixtures asociados a superficies retiradas.
- Persistencia: posibles migraciones Alembic conservadoras para tablas/columnas huérfanas, condicionadas a identidad de base de datos, respaldo y rollback.
- Contratos preservados: API FastAPI activa de proyectos, requests, auth, health/status, providers/health y budget; coordinación nativa, adaptadores de agentes, autenticación y autorización.
- No incluye despliegue productivo, cambios F7, nueva cola/scheduler, nueva implementación de OpenSpec ni modificación de specs históricas archivadas.
