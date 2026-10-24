## Context

mini me completó F1 (depuración de emulaciones y código obsoleto) y F2 (registro de proyectos, catálogos de proveedores/agentes, conexiones GitHub, onboarding Greenfield/incremental y cierre documental completo archivado). Los componentes utilizables tras F2 incluyen:
- `OpenSpecAdapter` (`src/minime/adapters/openspec.py`): inspección e inicialización oficial de integraciones y validación estricta de cambios.
- `native_openspec_apply.py`: resolución y validación de la presencia de workflows oficiales instalados.
- `AgentProcessConfinement` (`src/minime/services/agent_confinement.py`): aislamiento y sandbox de procesos en worktree autorizado.
- `WorktreeManager` (`src/minime/services/worktree_manager.py`): creación y ciclo de vida de worktrees aislados bajo la raíz administrada configurable del proyecto.
- `GitHubAdapter` (`src/minime/adapters/github.py`): operaciones REST de GitHub App, ramas, PRs, issues y comentarios.
- `ProjectService`, `ProjectCatalogService`, `ProjectConnectionService`: configuración por proyecto de roles, conexiones y políticas.
- `CapacityLifecycleService` y `BudgetService`: preflights de salud, cuotas, presupuesto y disponibilidad de proveedores.
- Persistencia PostgreSQL: modelos de `orchestration_runs`, `jobs`, `orchestration_stage_events`, `orchestration_worktree_ownership` y `durable_sagas`.

F3 debe conectar estos componentes en un flujo orquestado autónomo y real gobernado por las decisiones del Issue #171. Véase `proposal.md` para la motivación.

## Goals / Non-Goals

**Goals:**
- Implementar la selección FIFO remota de GitHub Issues con paginación real, exclusión de `disabled` y dependencias explícitas no resueltas, y unicidad de a lo sumo un Request activo en ejecución por proyecto (permitiendo proyectos sin trabajo elegible).
- Coordinar el ciclo de Propose: preparación Git (`request-<numero>-<slug-kebab>`) en la raíz administrada configurable mediante `WorktreeManager`, Explore oficial por el agente de pensamiento, Propose nativo oficial, Validate estricto por CLI con autocorrección, evaluación de complejidad por LLM y revisión independiente de propuesta para alta complejidad.
- Coordinar el ciclo de Apply y Verify: ejecución de OpenSpec Apply oficial por el agente ejecutor, diseño y ejecución obligatoria de pruebas unitarias/E2E reales, Verify oficial ejecutado por el propio ejecutor, bucle de corrección en fallos de Verify y revisión independiente de código para alta complejidad.
- Gestionar dos Pull Requests mediante punto de invocación de skill con contrato funcional mínimo en F3: primer PR de implementación con merge automático para complejidad baja/moderada y acuse informativo humano («Estoy enterado») para alta complejidad; preparación de rama y worktree frescos para cierre documental en la raíz administrada; ejecución de OpenSpec Sync y Archive oficiales por el agente de pensamiento; segundo PR documental con merge automático; y cierre remoto del issue con transición FIFO al siguiente.
- Mantener continuidad estricta: los fallos recuperables, límites de corrección y esperas de capacidad preservan los artefactos y el Worktree sin seleccionar silenciosamente otro Request ni limpiar el espacio de trabajo; solo un cierre real o una cancelación gobernada y autorizada libera la ejecución.
- Mantener persistencia mínima, observabilidad y resiliencia ante caídas en PostgreSQL, respetando cuotas y el protocolo humano en español.
- Ejecutar pruebas E2E en un repositorio de pruebas autorizado y aislado (e.g. `mini-me-fixture`) sin alterar el repositorio operativo ni los Issues de mini me.
- Reconciliar la documentación canónica (`CONTRATO_RECTOR.md`, `BACKLOG.md`, `AGENTS.md` y `openspec/config.yaml`) con las decisiones funcionales de F3.

**Non-Goals:**
- No implementar una UI web/tablet/mobile (reservada para F5).
- No construir un catálogo generalizado de skills, harnesses o hooks (reservado para F4).
- No implementar soporte para Azure DevOps ni proveedores secundarios de tickets.
- No realizar despliegue productivo de mini me ni de proyectos gestionados (la política actual es no desplegar salvo autorización expresa del operador).
- No habilitar el scheduler heredado en background de forma automática.
- No ejecutar migraciones en la base de datos operativa de producción durante la fase de propuesta.
- No construir colas paralelas o tablas de backlog secundarias en PostgreSQL.

## Decisions

### 1. Reutilización y extensión de `GitHubAdapter` para intake y merge
- **Decisión:** Extender `GitHubAdapter` con soporte de paginación completa en `list_issues` y con el método `merge_pull_request` (`PUT /repos/{owner}/{repo}/pulls/{pull_number}/merge`), manteniendo la separación entre la fuente de tickets y el proveedor Git/PR. La detección de dependencias examina únicamente relaciones explícitas formales admitidas por el proveedor (directivas `depends on #...`, `blocked by #...` o task lists de dependencias en el cuerpo del Issue), ignorando menciones casuales o referencias cruzadas no bloqueantes.
- **Razón:** Satisface el principio DRY y evita introducir librerías externas o adaptadores paralelos, aprovechando la autenticación GitHub App ya existente.
- **Alternativas consideradas:** Usar PyGithub u octokit; descartadas por violar la política de mínimas dependencias y añadir capas redundantes.

### 2. Servicio de orquestación cohesivo (`NativeOrchestrationCoordinator`)
- **Decisión:** Implementar un servicio modular y pequeño (`NativeOrchestrationCoordinator`) que coordina secuencialmente las etapas del Request (Explore → Propose → Validate → Complejidad → Revisión Propuesta → Apply → Pruebas → Verify → Revisión Código → PR1 → DocClose → Sync/Archive → PR2 → Cierre) persistiendo transiciones en `orchestration_runs`. El intake de issues se apoya en `RemoteRequestIntakeService` sin fragmentar el núcleo en múltiples microservicios innecesarios.
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

### 5. Integración de skill para preparación de Pull Requests y política de merge
- **Decisión:** La preparación del Pull Request (tanto de implementación como documental) se delega a una invocación de skill con un contrato mínimo y operativo en F3 (insumos: repositorio, rama base, rama head, título, resumen estructurado y SHA candidato verificado; salida: número de PR y URL). F3 deja la invocación funcional real para completar su E2E sin depender de F4, mientras que el catálogo completo de skills, harnesses y hooks se refinará en F4.
- **Política de merge:**
  1. *Primer PR:* De `request-<numero>-<slug>` a `main`. Baja/moderada: merge automático por mini me. Alta: estado `HUMAN REQUIRED` exclusivamente para acuse «Estoy enterado» con resumen en español; tras acuse, mini me ejecuta el merge.
  2. *Segundo PR:* De `doc-close-<numero>-<slug>` a `main`. Creado desde `main` actualizado tras la fusión del primer PR. El agente de pensamiento ejecuta Sync y Archive nativos. Merge automático por mini me siempre.
- **Razón:** La preparación vía skill garantiza extensibilidad sin anticipar prematuramente el catálogo de F4.

### 6. Continuidad estricta y preservación de Worktrees ante fallos recuperables
- **Decisión:** Un Request en ejecución conserva su continuidad y el bloqueo activo del proyecto. Ante fallos técnicos, límites de corrección o esperas de capacidad (`WAITING_CAPACITY`), el sistema preserva el Worktree, los artefactos generados y las referencias de estado en PostgreSQL; NUNCA abandona el Request para seleccionar silenciosamente otro ni destruye el Worktree.
- **Regla de liberación:** Únicamente tras la confirmación remota del segundo merge (cierre exitoso) o mediante una acción explícita de cancelación autorizada por el operador (`CANCELLED`), se libera el bloqueo del proyecto y se procede a la limpieza gobernada del Worktree.

### 7. Respeto a la raíz administrada real y pruebas E2E aisladas
- **Decisión:** La ubicación física de los Worktrees se resuelve dinámicamente mediante `worktree_manager.resolve_worktree_parent_dir(project_id)`, respetando la configuración del proyecto y las protecciones de `ManagedWorkspaceGuard`, sin imponer `.minime/worktrees/` como ruta fija si el proyecto define otra raíz administrada.
- **Aislamiento de pruebas:** Las pruebas E2E que involucren creación y fusión de PRs o cierre de issues operan contra un repositorio de pruebas aislado (e.g. `mini-me-fixture`), garantizando que jamás se alteren los issues ni la rama `main` operativa de `silverberdi/mini-me`.

### 8. Reconciliación canónica documental dentro del Change F3
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
  → *Mitigación:* Preflight de capacidad y presupuesto antes de cada invocación; si se agota, entrar en `WAITING_CAPACITY` preservando el estado y el worktree sin quemar saldo en reintentos ciegos.

- **[Risk: Conflictos de Git o Worktrees huérfanos tras interrupciones]**  
  → *Mitigación:* Trabajo aislado bajo la raíz administrada configurada, preservación para reanudación, verificación estricta de la identidad del candidate commit SHA antes de cualquier merge, y limpieza únicamente tras cierre confirmado o cancelación autorizada.

- **[Risk: Bucle infinito en correcciones de Verify o revisiones]**  
  → *Mitigación:* Límite finito de intentos configurado por proyecto (e.g. máximo 3 intentos de corrección); si se supera el límite, el cambio se detiene en un estado bloqueado preservando el worktree para inspección humana.

## Migration Plan

> [!IMPORTANT]
> Este plan describe el diseño técnico de la persistencia requerida por F3. **NO autoriza la ejecución de migraciones en la base de datos operativa de producción ni el despliegue de servicios en mini me.** La política vigente prohíbe despliegues y migraciones productivas sin autorización expresa del operador. El scheduler permanece deshabilitado.

1. **Alembic:** Diseñar una migración conservadora que incorpore campos indispensables si se requieren (por ejemplo, registrar el acuse humano «Estoy enterado» o vincular el segundo PR documental en `orchestration_runs`), verificando reversibilidad con `downgrade`.
2. **Registro de comandos CLI / API:** Registrar los nuevos comandos en la CLI de mini me (`minime request run <project_id>`) y endpoints REST correspondientes sin activar procesos en background ni scheduler.
3. **Rollback y preservación:** Si la orquestación falla, el trabajo activo se preserva en su worktree y checkpoint para permitir la reanudación; los datos de configuración de F2 permanecen intactos. Únicamente una cancelación explícita del operador limpia el worktree y libera el bloqueo.

## Open Questions

Ninguna. Todas las decisiones arquitectónicas y funcionales fueron resueltas durante el refinamiento del Issue #171 y confirmadas por el operador.
