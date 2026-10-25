# F2 — Punto de continuación ejecutable (no es otro Change)

**Autoridad:** Issue [#170](https://github.com/silverberdi/mini-me/issues/170), `docs/CONTRATO_RECTOR.md` v1.2, y `proposal.md`, `design.md`, las 7 delta specs y `tasks.md` de **este mismo** Change. No añadir criterios ni cambiar alcance. **PR de implementación único:** [#178](https://github.com/silverberdi/mini-me/pull/178), rama `openspec/gacela-02-proyectos`. El PR debe seguir Draft mientras no esté completo.

> Este archivo es solo un índice de reanudación para las sesiones de agentes. NO es una especificación nueva, autoriza gasto, ni reemplaza los artefactos OpenSpec. La evidencia de tareas se determina siempre leyendo `tasks.md` **en el HEAD remoto vigente**, no copiando el porcentaje guardado aquí. No convertir su actualización en una tarea ni en una entrega parcial.

## Antes de actuar, en cualquier sesión

1. Leer `AGENTS.md`, `docs/CONTRATO_RECTOR.md`, Issue #170 y el `proposal.md`, `design.md`, `tasks.md` y specs **existentes** de `gacela-02-proyectos`.
2. Confirmar repo, rama, remoto, HEAD, worktree y archivos locales ajenos; hacer fast-forward desde `origin/openspec/gacela-02-proyectos` sin sobrescribir archivos ajenos ni sustituir el Change. Leer PR #178 para hallazgos y autorizaciones.
3. Enumerar tareas pendientes desde `tasks.md`. Continuar `$openspec-apply-change gacela-02-proyectos` (o equivalente oficial **instalado** del agente), **implementando código**, no reportes. Commit y push durante el trabajo; **seguir después del push**.
4. Detenerse solo ante bloqueo real demostrado, después de completar todas las demás tareas independientes. No consumir cuota no autorizada; no tocar PostgreSQL operativo, activar scheduler, hacer merge ni crear nuevos Changes/PR de implementación.

## Anclas de código: no redescubrir el mapa

- **Coordinador F2 nuevo:** `src/minime/services/greenfield_bootstrap.py` → `GreenfieldBootstrapCoordinator.bootstrap()`, `add_context()`, `_run_after_project_creation()`, `_run_thinking_agent()`; orquesta ZIP→repo/worktree→OpenSpec→agente→push/PR y continuación incremental. Revisar integridad funcional y seguridad, no asumir E2E probado.
- **Ingesta ZIP:** `src/minime/services/context_archive.py` → `ContextArchiveExtractor`; fixture `tests/fixtures/gacela-02-proyectos/console-sorter-context.{md,zip}`; **solo** acredita recepción/extracción, no preparación por agente ni GitHub.
- **Registro, migración y perfiles:** `src/minime/services/project_service.py`, `src/minime/domain/models.py`, `src/minime/db/{models,repository}.py`, `alembic/versions/f2_project_configuration.py`.
- **Conexiones y secretos:** `src/minime/services/project_connection_service.py`, `project_credential_store.py`, `src/minime/adapters/github.py`. Auth GitHub App de entorno: `MINIME_GITHUB_APP_ID`, `MINIME_GITHUB_INSTALLATION_ID`, `MINIME_GITHUB_PRIVATE_KEY_PATH`; configuración histórica en `/etc/minime/minime.env` del servidor (observar de modo seguro, jamás copiar/mostrar valores). El código soporta credenciales project-owned. No asumir que la sesión local hereda credenciales del servicio.
- **Agentes / OpenSpec oficiales:** `src/minime/services/project_catalog_service.py`, `src/minime/adapters/openspec.py`, `src/minime/services/implementer_runner.py`, `src/minime/config.py`. Verificar perfil, CLI, modelo/esfuerzo y skills instaladas en el **workspace objetivo**.
- **Aislamiento / binding:** `src/minime/services/project_onboarding_service.py` (guardas aprovechables de legado), `src/minime/services/workspace_guard.py`, `src/minime/services/worktree_manager.py`, `src/minime/services/agent_confinement.py`.
- **Entradas API/CLI:** `src/minime/api/app.py` (incluye `POST /api/v1/projects/greenfield/bootstrap` y `POST /api/v1/projects/{project_id}/context`), `src/minime/cli/main.py` (incluye `project bootstrap` y `project add-context`). Integran coordinador, no equivalen a E2E.
- **Dos registros históricos:** `mini-me` ↔ `silverberdi/mini-me`, y `mini-me-fixture` ↔ `silverberdi/mini-me-r01-e2e-20261014`. Hay identidad/bindings/contexto históricos que no se deben destruir, ni obligar a bootstrap ZIP/PR retroactivo. Ver sección J del Issue #170 y censos de `design.md`.

## Distinción imprescindible: falta real vs recurso ya existente

- **Fixture de GitHub:** existe `silverberdi/mini-me-r01-e2e-20261014` (repo privado, `main`, accesible por la conexión GitHub actual; evidencia R01 en `openspec/changes/real-openspec-agent-execution/evidence/provider-capacity-strategy-2026-10-14.md`). **Que exista NO significa que esté autorizado reutilizarlo para un E2E destructivo o producir merges en F2.** Verificar autorización específica, aislamiento y posibilidad de usarlo sin afectar la evidencia histórica. No afirmar «no existe repositorio» sin inspeccionarlo.
- **Credenciales GitHub App:** las variables y la configuración del servicio existen como diseño/observación anterior; la autenticación vigente, permisos de la App y accesibilidad desde el proceso que ejecutará F2 **no están verificados**. No solicitar crear otra GitHub App por no encontrar las credenciales en la terminal de una sesión local. Preflight read-only bajo identidad de servicio autorizada, con errores sanitizados.
- **`/run/minime-agent`:** en `agent_confinement.py`, `AgentProcessConfinement.SANDBOX_RUNTIME_ROOT` es una **ruta dentro del sandbox**. `AgentRuntimeState` crea un directorio host temporal privado y Bubblewrap monta el bind bajo `/run/minime-agent` después de un `--tmpfs /run`. No concluir que alguien debe aprovisionar manualmente esa ruta en el host. Si falla, registrar error concreto del runner/confinamiento, plataforma, perfil, ruta y evidencia sin secretos; arreglar la integración legítima sin desactivar aislamiento.
- **Real E2E y cuotas:** el costo de una invocación real de agente y los merges/pruebas sobre GitHub requieren autorización vigente. La evidencia antigua de R01 o cuota observada anteriormente no autoriza automáticamente F2. La carencia de esa autorización impide solo operaciones externas cubiertas por ella, **no** terminar las demás tareas de código y pruebas locales.

## Prioridad funcional para las siguientes sesiones

1. Completar y probar la ruta **vertical** GREENFIELD de extremo a extremo en código, con reanudación segura, integridad de fuentes, PR y merge observado; cubrir sus contratos deterministas sin declarar E2E real.
2. Completar contexto incremental, contradicciones, idempotencia y reconciliación tras interrupciones.
3. Cerrar paridad y eliminación segura de lectores/escritores legacy, migración de los dos proyectos históricos, API/CLI y verificaciones de roles/conexiones.
4. Ejecutar pruebas integrales locales, matriz G1–G15 y E2E con agente/GitHub reales **solo** cuando existan identidad, destino, gasto y autorización confirmados.

**Última fotografía verificada al redactar este índice:** PR #178 HEAD `257549fe1db91806a63ffcf4eccd95a112c936cc`, `26/48` tareas marcadas, `22` pendientes; el agente reportó 71 pruebas focalizadas PASS, Ruff/OpenSpec strict/git diff check PASS, **sin E2E real**. Esta fotografía caduca tras el próximo commit; consultar el remoto. La descripción del PR está desactualizada y no es evidencia más reciente que el HEAD y el propio `tasks.md`.

**Entrega aceptable:** F2 completa, validada, publicada y lista para revisión humana, o bloqueo externo preciso después de ejecutar todo lo independiente. Ni un reporte de avance ni una actualización de este archivo son entregas.
