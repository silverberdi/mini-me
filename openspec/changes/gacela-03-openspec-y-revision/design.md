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
- Coordinar el ciclo de Propose: preparación Git (`request-<numero>-<slug-kebab>`) en la raíz administrada configurable mediante `WorktreeManager`, resolución dinámica de Explore oficial para el agente de pensamiento, Propose nativo oficial resuelto, Validate estricto por CLI con autocorrección, evaluación de complejidad por LLM y revisión independiente de propuesta para alta complejidad.
- Coordinar el ciclo de Apply y Verify: resolución desacoplada de workflows según agente y worktree; verificación obligatoria de la presencia nativa de Verify en el ejecutor antes del despacho (bloqueo *fail-closed* si falta); ejecución de OpenSpec Apply oficial por el agente ejecutor, diseño y ejecución obligatoria de pruebas unitarias/E2E reales, Verify oficial ejecutado por el propio ejecutor, bucle de corrección en fallos de Verify y revisión independiente de código para alta complejidad.
- Entregar en F3 la capacidad mínima operativa de preparación de Pull Requests (`minime-pr-preparer`) con contrato funcional concreto (entrada: proyecto, repositorio, tipo de PR1/PR2, request, ramas, SHA candidato, evidencias; salida: título, cuerpo Markdown formateado y referencias), eliminando la dependencia externa de F4 para completar el ciclo; primer PR de implementación con merge automático para baja/moderada y acuse informativo humano («Estoy enterado») para alta complejidad; preparación de rama y worktree frescos para cierre documental en la raíz administrada; ejecución de OpenSpec Sync y Archive oficiales resueltos para el agente de pensamiento; segundo PR documental con merge automático; y cierre remoto del issue con transición FIFO al siguiente.
- Mantener continuidad estricta: los fallos recuperables, límites de corrección y esperas de capacidad preservan los artefactos y el Worktree sin seleccionar silenciosamente otro Request ni limpiar el espacio de trabajo; solo un cierre real o una cancelación gobernada y autorizada libera la ejecución.
- Mantener persistencia mínima, observabilidad y resiliencia ante caídas en PostgreSQL, respetando cuotas y el protocolo humano en español.
- Ejecutar pruebas E2E en un repositorio de pruebas autorizado y aislado (e.g. `mini-me-fixture`) demostrando la resolución real de workflows y sin alterar el repositorio operativo ni los Issues de mini me.
- Reconciliar la documentación canónica (`CONTRATO_RECTOR.md`, `BACKLOG.md`, `AGENTS.md` y `openspec/config.yaml`) con las decisiones funcionales de F3.

**Non-Goals:**
- No implementar una UI web/tablet/mobile (reservada para F5).
- No construir un catálogo generalizado de skills, harnesses o hooks (reservado para F4; F3 solo entrega la skill mínima de PR).
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
- **Decisión:** Implementar un servicio modular y pequeño (`NativeOrchestrationCoordinator`) que coordina secuencialmente las etapas del Request (Explore → Propose → Validate → Complejidad → Revisión Propuesta → Apply → Pruebas → Verify → Revisión Código → PR1 → DocClose → Sync/Archive → PR2 → Cierre) persistiendo transiciones en `orchestration_runs`. El coordinador delega cada etapa operativa a los agentes configurados mediante `CliAgentRunner` y adaptadores oficiales, prohibiendo taxativamente:
  1. Emular Explore con respuestas simuladas o diccionarios estáticos.
  2. Emular Propose generando plantillas de texto en Python en lugar del workflow nativo.
  3. Emular revisiones independientes con retornos estáticos `return True` o stubs vacíos.
  4. Emular Apply simulando cambios de tareas mediante expresiones regulares en `tasks.md`.
  5. Emular Sync o Archive con llamadas directas a `shutil.move` u operaciones arbitrarias de ficheros en Python.
  El intake de issues se apoya en `RemoteRequestIntakeService` sin fragmentar el núcleo en múltiples microservicios innecesarios.
- **Razón:** Cumple con la directriz de «la gacela, no el paquidermo»: lógica clara, determinista y orientada a objetos sin crear motores genéricos de workflows ni sagas sobre-dimensionadas, garantizando ejecuciones 100% auténticas y demostrables.
- **Alternativas consideradas:** Reutilizar o extender `SagaEngine` para cada sub-paso de agente; descartado porque las sagas añaden overhead de compensación innecesario para un flujo lineal donde la recuperación se basa en inspeccionar el estado observable de Git y OpenSpec.

### 3. Ejecutor unificado de agentes (`CliAgentRunner`)
- **Decisión:** Consolidar el despacho de procesos de agentes en un runner reutilizable (`CliAgentRunner`) que maneja los perfiles de invocación (`CliInvocationProfile`), el confinamiento en sandbox (`AgentProcessConfinement`), el timeout y la captura de trazas para los roles de pensamiento, ejecución y revisión independiente. Todas las invocaciones a agentes capturan código de salida, stdout y stderr, registrando la evidencia observable en la base de datos o logs durables.
- **Razón:** Elimina la duplicación entre `CliImplementerRunner` y `CliReviewerRunner`, permitiendo invocar al agente de pensamiento con el mismo rigor de confinamiento y captura que a los demás roles.
- **Alternativas consideradas:** Crear tres clases de runner separadas (`ThinkerRunner`, `ImplementerRunner`, `ReviewerRunner`); descartado porque la mecánica de ejecución subprocess y sandbox es común a todos los roles.

### 4. Resolución e invocación nativa estricta de OpenSpec
- **Decisión:** Mini me resuelve dinámicamente cada operación oficial de OpenSpec (Explore, Propose, Apply, Verify, Sync, Archive) y el comando CLI (`openspec validate`) sin hardcodear comandos universales ni asumir la sintaxis de un único proveedor. La resolución de cada etapa se determina estrictamente a partir de:
  1. *Agente configurado para el rol:* agente asociado a la etapa (`thinking`, `execution`/`implementer`, `independent_review`) validado contra el catálogo de perfiles.
  2. *Versión oficial de OpenSpec instalada:* inspeccionada mediante `OpenSpecAdapter.inspect_cli()`.
  3. *Workflows realmente instalados en el Worktree:* descubrimiento estricto mediante `OpenSpecAdapter.inspect_integrations()` y verificación de rutas libres de symlinks (e.g. `.agent/workflows/opsx-<op>.md` para Antigravity vs `.agents/skills/openspec-<op>/SKILL.md` para Codex, reutilizando `native_openspec_apply.py`).
  4. *Capacidades verificadas del perfil:* roles de edición (`file_edit_roles`) para pensamiento y ejecución, y roles de solo lectura (`read_only_roles`) para revisión, validados por `ProjectCatalogService.validate_project_profiles()`.
  5. *Transporte nativo del proveedor:* despacho mediante `stdin` o `argument` según `CliInvocationProfile.prompt_transport`, utilizando la sintaxis nativa correspondiente (`/opsx-...` en Antigravity, `$openspec-...` en Codex) como ejemplos específicos de proveedor y nunca como comandos universales.
- **Verificación previa de Verify nativo:** Antes de despachar al implementador a Apply o Verify, el coordinador comprueba obligatoriamente que el agente de ejecución dispone del workflow oficial de Verify (`opsx-verify` o `openspec-verify-change`) instalado y verificado en el worktree. Si el workflow no está presente o no es compatible, el sistema bloquea inmediatamente en *fail-closed*, reporta la capacidad ausente y preserva el Request y su worktree para intervención o remediación.
- **Prohibición de sustitutos:** Mini me jamás emula OpenSpec, no genera Markdown en Python, no reemplaza Verify con comandos de shell supuestos ni construye un segundo catálogo paralelo.
- **Razón:** Satisface las observaciones de la revisión independiente de Codex, eliminando el acoplamiento rígido a Antigravity y asegurando que Codex o cualquier proveedor configurado ejecute su integración nativa real.

### 5. Skill mínima operativa de preparación de Pull Requests y política de merge
- **Decisión:** F3 entrega la skill mínima de preparación de Pull Requests (`minime-pr-preparer`), proporcionando la capacidad operativa completa para preparar el primer PR (implementación) y el segundo PR (documental) sin depender de F4. F4 consolidará más adelante el catálogo generalizado de skills, harnesses y hooks.
- **Contrato de la skill (`minime-pr-preparer`):**
  - *Entrada estructurada:*
    - Proyecto y repositorio autorizados.
    - Tipo de PR: `implementation` (PR1) o `documentation` (PR2).
    - Request original (número de issue, título, cuerpo).
    - Rama base (`main`) y rama candidata (`request-...` o `doc-close-...`).
    - Commit SHA exacto del candidato verificado.
    - Resumen estructurado del cambio y área afectada.
    - Evidencia de pruebas/verificación correspondiente (salida de pytest/E2E para PR1; evidencia de OpenSpec Sync/Archive para PR2).
    - Referencia canónica al Change de OpenSpec (`gacela-03-openspec-y-revision`).
  - *Salida estructurada:*
    - Título estandarizado del PR.
    - Cuerpo descriptivo en Markdown estructurado (resumen, componentes modificados, cobertura de pruebas, referencia informativa al Issue como `Ref #...` o `Addresses #...`, referencias OpenSpec).
    - Metadatos suficientes para que el adaptador publique el PR sin ambigüedades.
- **Prohibición de palabras clave de cierre automático en PR1 y PR2:**
  - La skill `minime-pr-preparer` omite taxativamente cualquier directiva de cierre automático de GitHub (`Fixes #...`, `Closes #...`, `Resolves #...` y variantes equivalentes) en los contenidos preparados para PR1 y PR2. El cierre automático del Issue con el merge del primer PR violaría el contrato rector de F3, que exige completar Sync/Archive y verificar el merge del segundo PR antes del cierre.
  - El cierre del Request se efectúa de manera exclusiva y gobernada por el coordinador a través de `GitHubAdapter.close_issue` tras confirmar el merge remoto de PR2.
- **Separación de responsabilidades y permisos:**
  - La skill prepara exclusivamente el contenido textual y semántico del PR.
  - `GitHubAdapter` ejecuta de forma determinista las operaciones de Git y GitHub API: push de la rama, creación del PR (`pull_request.create`), consulta de estado y protecciones, y ejecución del merge (`merge_pull_request`).
  - La skill y el agente no reciben tokens ni permisos de GitHub adicionales innecesarios; las credenciales seguras de GitHub App permanecen confinadas dentro de `GitHubAdapter`.
- **Reconciliación con guardianes heredados (`minime-git-workspace-guardian` y `minime-github-work-management-guardian`):**
  - Las directivas de los guardianes existentes («create a PR for executable work, never merge» y «Human merge is mandatory») regulan la conducta autónoma no coordinada de los agentes en el worktree, impidiendo que un agente ejecute `git merge` local o fusione ramas de forma arbitraria en la terminal.
  - No colisionan con el coordinador de mini me, que ejecuta el merge remoto gobernado vía GitHub API respetando la política autorizada de F3. El prompt de invocación al agente delimita explícitamente que la fusión remota es potestad exclusiva del coordinador mini me.
- **Política de merge:**
  1. *Primer PR (implementación):* De `request-<numero>-<slug>` a `main`. Complejidad baja/moderada: merge automático por mini me. Complejidad alta: estado `HUMAN REQUIRED` exclusivamente para acuse informativo «Estoy enterado» con resumen en español; tras confirmación del acuse, mini me ejecuta el merge.
  2. *Segundo PR (documental):* De `doc-close-<numero>-<slug>` a `main` desde el commit fusionado de `main`. El agente de pensamiento ejecuta Sync y Archive nativos. Merge automático por mini me siempre.
- **Razón:** La entrega de la skill mínima en F3 desbloquea la prueba E2E completa sin depender de F4, manteniendo un diseño limpio y desacoplado.

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
