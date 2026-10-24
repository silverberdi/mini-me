## Context

mini me completó F1 (depuración de emulaciones y código obsoleto) y F2 (registro de proyectos, catálogos de proveedores/agentes, conexiones GitHub y onboarding Greenfield/incremental). Los componentes utilizables tras F2 incluyen:
- `OpenSpecAdapter` (`src/minime/adapters/openspec.py`): inspección e inicialización oficial de integraciones y validación estricta de cambios.
- `native_openspec_apply.py`: resolución y validación de la presencia de workflows oficiales instalados.
- `AgentProcessConfinement` (`src/minime/services/agent_confinement.py`): aislamiento y sandbox de procesos en worktree autorizado.
- `WorktreeManager` (`src/minime/services/worktree_manager.py`): creación y ciclo de vida de worktrees aislados bajo `.minime/worktrees/`.
- `GitHubAdapter` (`src/minime/adapters/github.py`): operaciones REST de GitHub App, ramas, PRs, issues y comentarios.
- `ProjectService`, `ProjectCatalogService`, `ProjectConnectionService`: configuración por proyecto de roles, conexiones y políticas.
- `CapacityLifecycleService` y `BudgetService`: preflights de salud, cuotas, presupuesto y disponibilidad de proveedores.
- Persistencia PostgreSQL: modelos de `orchestration_runs`, `jobs`, `orchestration_stage_events`, `orchestration_worktree_ownership` y `durable_sagas`.

F3 debe conectar estos componentes en un flujo orquestado autónomo y real gobernado por las decisiones del Issue #171. Véase `proposal.md` para la motivación.

## Goals / Non-Goals

**Goals:**
- Implementar la selección FIFO remota de GitHub Issues con paginación real, exclusión de `disabled` y dependencias no resueltas, y unicidad de ejecución por proyecto.
- Coordinar el ciclo de Propose: preparación Git (`request-<numero>-<slug-kebab>`), Explore oficial por el agente de pensamiento, Propose nativo oficial, Validate estricto por CLI con autocorrección, evaluación de complejidad por LLM y revisión independiente de propuesta para alta complejidad.
- Coordinar el ciclo de Apply y Verify: ejecución de OpenSpec Apply oficial por el agente ejecutor, diseño y ejecución obligatoria de pruebas unitarias/E2E reales, Verify oficial ejecutado por el propio ejecutor, bucle de corrección en fallos de Verify y revisión independiente de código para alta complejidad.
- Gestionar dos Pull Requests: primer PR de implementación con merge automático para complejidad baja/moderada y acuse informativo humano («Estoy enterado») para alta complejidad; preparación de rama y worktree frescos para cierre documental; ejecución de OpenSpec Sync y Archive oficiales por el agente de pensamiento; segundo PR documental con merge automático; y cierre remoto del issue con transición FIFO al siguiente.
- Mantener persistencia mínima, observabilidad y resiliencia ante caídas en PostgreSQL, respetando cuotas y el protocolo humano en español.
- Reconciliar la documentación canónica (`CONTRATO_RECTOR.md`, `BACKLOG.md`, `AGENTS.md` y `openspec/config.yaml`) con las decisiones funcionales de F3.

**Non-Goals:**
- No implementar una UI web/tablet/mobile (reservada para F5).
- No construir un catálogo generalizado de skills, harnesses o hooks (reservado para F4).
- No implementar soporte para Azure DevOps ni proveedores secundarios de tickets.
- No asumir el despliegue productivo (responsabilidad del CI/CD del proyecto).
- No habilitar el scheduler heredado en background de forma automática.
- No construir colas paralelas o tablas de backlog secundarias en PostgreSQL.

## Decisions

### 1. Reutilización y extensión de `GitHubAdapter` para intake y merge
- **Decisión:** Extender `GitHubAdapter` con soporte de paginación completa en `list_issues` y con el método `merge_pull_request` (`PUT /repos/{owner}/{repo}/pulls/{pull_number}/merge`), manteniendo la separación entre la fuente de tickets y el proveedor Git/PR.
- **Razón:** Satisface el principio DRY y evita introducir librerías externas o adaptadores paralelos, aprovechando la autenticación GitHub App ya existente.
- **Alternativas consideradas:** Usar PyGithub u octokit; descartadas por violar la política de mínimas dependencias y añadir capas redundantes.

### 2. Servicio de orquestación cohesivo (`NativeOrchestrationCoordinator`)
- **Decisión:** Implementar un servicio modular y pequeño (`NativeOrchestrationCoordinator`) que coordina secuencialmente las etapas del Request (Explore → Propose → Validate → Complejidad → Revisión Propuesta → Apply → Pruebas → Verify → Revisión Código → PR1 → DocClose → Sync/Archive → PR2 → Cierre) persistiendo transiciones en `orchestration_runs`.
- **Razón:** Cumple con la directriz de «la gacela, no el paquidermo»: lógica clara, determinista y orientada a objetos sin crear motores genéricos de workflows ni sagas sobre-dimensionadas.
- **Alternativas consideradas:** Reutilizar o extender `SagaEngine` para cada sub-paso de agente; descartado porque las sagas añaden overhead de compensación innecesario para un flujo lineal donde la recuperación se basa en inspeccionar el estado observable de Git y OpenSpec.

### 3. Ejecutor unificado de agentes (`CliAgentRunner`)
- **Decisión:** Consolidar el despacho de procesos de agentes en un runner reutilizable (`CliAgentRunner`) que maneja los perfiles de invocación (`CliInvocationProfile`), el confinamiento en sandbox (`AgentProcessConfinement`), el timeout y la captura de trazas para los roles de pensamiento, ejecución y revisión independiente.
- **Razón:** Elimina la duplicación entre `CliImplementerRunner` y `CliReviewerRunner`, permitiendo invocar al agente de pensamiento con el mismo rigor de confinamiento y captura que a los demás roles.
- **Alternativas consideradas:** Crear tres clases de runner separadas (`ThinkerRunner`, `ImplementerRunner`, `ReviewerRunner`); descartado porque la mecánica de ejecución subprocess y sandbox es común a todos los roles.

### 4. Invocación nativa estricta de OpenSpec
- **Decisión:** Mini me únicamente invoca los workflows oficiales instalados (`opsx-explore`, `opsx-propose`, `opsx-apply`, `opsx-verify`, `opsx-sync`, `opsx-archive`) o el comando CLI (`openspec validate`). Mini me nunca genera ni manipula contenido Markdown ni estructura interna de cambios.
- **Razón:** Cumple la prohibición explícita del Contrato Rector v1.2 y el Issue #171.
- **Alternativas consideradas:** Generar plantillas preliminares en Python; estrictamente prohibido.

### 5. Arquitectura de dos Pull Requests y política de merge por complejidad
- **Decisión:**
  1. *Primer PR:* De `request-<numero>-<slug>` a `main`. Baja/moderada: merge automático por mini me. Alta: estado `HUMAN REQUIRED` exclusivamente para acuse «Estoy enterado» con resumen en español; tras acuse, mini me ejecuta el merge.
  2. *Segundo PR:* De `doc-close-<numero>-<slug>` a `main`. Creado desde `main` actualizado tras la fusión del primer PR. El agente de pensamiento ejecuta Sync y Archive nativos. Merge automático por mini me siempre.
- **Razón:** El merge del primer PR es el punto de integración del código; el segundo PR garantiza que la documentación en `main` refleje los artefactos archivados sin riesgo de conflictos de merge en la implementación.
- **Alternativas consideradas:** Ejecutar sync/archive en la misma rama antes del primer merge; descartado porque el sync/archive debe ejecutarse contra la versión fusionada de `main` para evitar divergencia de specs principales.

### 6. Reconciliación canónica documental dentro del Change F3
- **Decisión:** Actualizar directamente `docs/CONTRATO_RECTOR.md`, `docs/BACKLOG.md`, `AGENTS.md` y `openspec/config.yaml` reflejando las decisiones acordadas el 22-10-2026 en el Issue #171:
  - Explore obligatorio previo a Propose.
  - Revisión independiente de propuesta solo para alta complejidad.
  - Verify ejecutado por el agente ejecutor.
  - Revisión independiente de implementación solo para alta complejidad.
  - Merge automático del primer PR para baja/moderada; acuse humano «Estoy enterado» para alta.
  - Segundo PR documental con merge automático.
- **Razón:** El Issue #171 exige expresamente que F3 contenga su propia reconciliación canónica sin crear un Change adicional.

## Risks / Trade-offs

- **[Risk: Tiempos de ejecución prolongados en agentes que agotan timeouts]**  
  → *Mitigación:* Timeouts configurables por etapa, preservación atómica de estado en PostgreSQL y reanudación idempotente desde el último checkpoint verificado.

- **[Risk: Agotamiento de cuota o límites de tasa en proveedores LLM o GitHub]**  
  → *Mitigación:* Preflight de capacidad y presupuesto antes de cada invocación; si se agota, entrar en `WAITING_CAPACITY` preservando el estado sin quemar saldo en reintentos ciegos.

- **[Risk: Conflictos de Git o Worktrees huérfanos tras interrupciones]**  
  → *Mitigación:* Trabajo aislado bajo `.minime/worktrees/`, limpieza segura al finalizar, y verificación estricta de la identidad del candidate commit SHA antes de cualquier merge.

- **[Risk: Bucle infinito en correcciones de Verify o revisiones]**  
  → *Mitigación:* Límite finito de intentos configurado por proyecto (e.g. máximo 3 intentos de corrección); si se supera el límite, el cambio se detiene en un estado bloqueado visible para el operador.

## Migration Plan

1. **Alembic:** Diseñar y aplicar una migración conservadora que incorpore campos indispensables si se requieren (por ejemplo, registrar el acuse humano «Estoy enterado» o vincular el segundo PR documental en `orchestration_runs`), verificando reversibilidad con `downgrade`.
2. **Despliegue operativo:** Registrar los nuevos comandos en la CLI de mini me (`minime request run <project_id>`) y endpoints REST correspondientes.
3. **Rollback:** Si la orquestación falla, el trabajo activo se libera limpiando el worktree temporal; los datos de configuración de F2 permanecen intactos.

## Open Questions

Ninguna. Todas las decisiones arquitectónicas y funcionales fueron resueltas durante el refinamiento del Issue #171.
