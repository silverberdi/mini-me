# mini me — Contrato rector de producto y arquitectura

**Versión 2.0 — 3 de noviembre de 2026.**
**Autoridad:** este documento es la dirección funcional y arquitectónica de mini me; sustituye las decisiones incompatibles de planes, specs, fichas y contratos históricos, incluida la versión 1.3. La implementación existente NO se considera conforme por la sola publicación de este documento.
**Naturaleza:** instalación personal única, no producto comercial. A partir de esta versión, el trabajo se autoriza por **cambios discretos** (un Issue = un Change OpenSpec), sin numeración de fases ni tabla fija de Issues.
**Modelo de autorización:** el operador es la única autoridad que autoriza cambios. Cada cambio es un Issue con un único Change OpenSpec y un alcance cohesivo. La corrección de bloqueos del propio mini me es un cambio ordinario, no una "excepción".
**Estado:** actualización contractual documental sobre la v1.3. Este documento no autoriza por sí mismo crear cambios, desplegar, migrar, iniciar scheduler, consumir agentes ni fusionar PRs; cada cambio requiere autorización expresa del operador y su Change OpenSpec con gates humanos.

## 1. La gacela, no el paquidermo

mini me debe ser una aplicación pequeña, rápida, mantenible, extensible y, sobre todo, útil. Coordina agentes para convertir requerimientos externos en implementaciones verificadas, revisadas, fusionadas y archivadas mediante los workflows oficiales de OpenSpec. No programa ni razona en lugar de los agentes.

Principios no negociables: simplicidad; reutilización antes de crear; una responsabilidad por componente; configuración antes que valores hardcodeados; POO bien aplicada, SOLID y DRY; KISS y YAGNI; autonomía que evite al operador ser mensajero; observabilidad clara; E2E real; reducción activa de código, dependencias, estados y tablas sin utilidad. Entre soluciones equivalentes se adopta la más sencilla que preserva la seguridad y calidad.

**Prohibición:** mini me NO genera mediante plantillas propias proposal/design/specs/tasks, NO reimplementa propose/update/continue/apply/verify/sync/archive, NO fusiona Markdown o mueve directorios como sustituto del workflow OpenSpec, NO crea motores de razonamiento, ranking, clasificación o revisión propios, NO duplica la fuente de tickets en PostgreSQL y NO administra despliegues productivos. Puede leer artefactos, verificar resultados observables, proteger repositorios, controlar permisos/costos y coordinar Git.

## 2. Responsabilidades y fronteras

- **Proveedor de tickets:** fuente autoritativa de requerimientos, fechas, comentarios y cierre; GitHub Issues inicialmente; el frontend y el núcleo dependen de un contrato de tickets agnóstico al proveedor.
- **Git y proveedor de PR:** repositorios, ramas, worktrees, commits, diffs, PR y merges.
- **OpenSpec:** autoridad de comportamiento/diseño/tareas y de los workflows nativos usados por agentes.
- **Agentes:** pensamiento/propuesta/verify, ejecución/apply/correcciones, revisión independiente de solo lectura y respaldo compatible.
- **mini me:** configura proyectos, identifica y selecciona tickets, prepara worktrees, invoca agentes con skills oficiales, recibe evidencias, publica comentarios/PR, presenta decisiones, ejecuta operaciones Git autorizadas y reanuda trabajo. No produce contenido semántico OpenSpec ni código.
- **PostgreSQL:** configuración y mínimo estado operativo necesario para continuidad/idempotencia, autorizaciones y límites de gasto. Nunca es el backlog maestro.
- **CI/CD propio del proyecto:** todo despliegue productivo, fuera del alcance de mini me.

Una única API FastAPI, modular y con la UI consumiéndola. No segunda API ni microservicios.

## 3. Módulo de proyectos

Cada proyecto configura: nombre/id; repositorio y rama base (main por defecto); origen de tickets; ubicación/contexto OpenSpec; agente y modelo de pensamiento, ejecución, revisión independiente y respaldo; capacidad compatible con CLI/workflows por rol; skills existentes; esfuerzo; límite de correcciones; política sencilla de revisión de código; política de costo y estado activo/pausado. La activación/pausa administrativa no significa que exista pausa diferida del Run ni selección de un único proyecto ejecutor, salvo que esas capacidades estén implementadas y autorizadas como cambio.

**Contratos distintos para fuente de tickets y proveedor Git/PR** (pueden diferir). Fuente de tickets intercambiable mediante una interfaz mínima para listar/leer/crear/comentar/cerrar, pero SOLO GitHub se implementa inicialmente. NO construir ADO ni framework de plugins hasta existir necesidad.

Esfuerzo por defecto medio para propone/updates sustantivos, apply, verify y revisión; mínimo compatible para sync/archive. Estas asignaciones no autorizan optimizadores o escaladores automáticos. El respaldo necesita capacidad real del workflow y autorización de gasto; un API de texto no se considera CLI de edición de archivos. La identidad del autor de un candidato no puede certificar su propia revisión.

Al configurar contexto, reutilizar e instalar skills OpenSpec preexistentes; usar AGENTS.md y equivalentes específicos de agente para enlazar al contexto canónico, sin mantener copias divergentes, sobrescribir instrucciones existentes ni escribir en main sin la ruta Git autorizada. Skills de tickets/comentarios/PR/cierre **preexistentes o reutilizables**, seleccionadas por proyecto.

## 4. Flujo OpenSpec (una unidad de trabajo activa por proyecto)

Para un proyecto habilitado y **cuando exista admisión de trabajo autorizada**, consultar directamente tickets abiertos y elegibles en el origen remoto; **activar administrativamente un proyecto no dispara agentes, scheduler ni ticket alguno**. En esa admisión autorizada: orden ascendente por fecha de creación, desempate estable por ID; comenzar el más antiguo. No mantener cola duplicada ni usar scoring, envejecimiento, prioridades sintéticas o roadmap como orden alternativo. Si el ticket seleccionado queda bloqueado, conservarlo; no saltar silenciosamente a otro. El siguiente empieza cuando se haya completado el cierre documental y del ticket anterior.

**Explore (pensamiento):** indagar de forma autónoma el contexto del ticket, repositorio y archivos de diseño. Emitir READY TO PROPOSE si hay suficiente información, o pausar con HUMAN REQUIRED con opciones estructuradas en español si existe ambigüedad material irresoluble.

**Propose (pensamiento):** invocar workflow nativo de propuesta, obtener artefactos (`proposal.md`, `specs/`, `design.md`, `tasks.md`), ejecutar validación estricta CLI con autocorrección. Evaluar complejidad fundamentada (`low`, `moderate`, `high`). Para complejidad alta, invocar revisión independiente de solo lectura; para complejidad baja/moderada, avanzar directamente a Apply. La revisión debe **converger**: evaluar defectos sustantivos (corrección, seguridad, alcance) sobre los artefactos completos, sin re-flag de requisitos ya cubiertos ni peticiones de redacción o formato.

**Apply (ejecutor):** verificar previamente que el ejecutor dispone de Verify nativo instalado (bloqueo *fail-closed* si falta); ejecutar workflow nativo apply, diseñar y ejecutar obligatoriamente pruebas unitarias/E2E reales en el proyecto (exit code 0), implementar tareas de `tasks.md` y pasar a Verify. **Recuperación guiada:** ante un Apply parcial, reanudar sobre el mismo Change, rama, worktree y candidato mediante el workflow nativo, con un contexto correctivo basado en evidencia observada (Git y pruebas capturados por mini me, no por el relato del agente); repetir con límite por falta de progreso y un tope duro de intentos; detenerse *fail-closed* ante regresión de archivos, tareas, pruebas o identidad del candidato.

**Verify (ejecutor):** ejecutado por el mismo agente ejecutor mediante el workflow oficial OpenSpec Verify (y NO por el agente de pensamiento). Ante discrepancias, bucle de autocorrección con Apply. Al aprobar: baja/moderada pasa a preparación de PR; alta complejidad pasa a revisión independiente de código de solo lectura.

**Revisión independiente de código (condicional para alta complejidad):** agente de solo lectura contrasta ticket, propuesta, specs, diff y pruebas. Hallazgos → vuelta a Apply/Verify. Aprobación → preparación de PR.

**Preparación de PR y política de merge:** la skill mínima `minime-pr-preparer` usa referencias estrictamente informativas (`Addresses #...` o `Ref #...`), excluyendo taxativamente palabras de cierre automático (`Fixes`, `Closes`, `Resolves`).
- *Primer PR (implementación):* merge automático por mini me para baja/moderada; acuse informativo humano («Estoy enterado») para alta complejidad antes de que mini me ejecute el merge.
- *Rama documental y segundo PR:* tras confirmar merge de PR1, crear rama fresca `doc-close-<num>-<slug>` desde `main` actualizado en la raíz administrada; agente de pensamiento ejecuta Sync y Archive nativos; PR2 documental con merge automático incondicional por mini me.
- *Cierre remoto:* mini me cierra el Issue remoto únicamente tras verificar el merge de PR2, liberando el bloqueo y pasando al siguiente ticket FIFO.
- *Higiene de workspace:* al completar o cancelar un run, mini me limpia su worktree y su registro de propiedad; no deja worktrees huérfanos que bloqueen runs futuros sobre el mismo cambio.

## 5. Intervención humana asistida

En Propose, Apply y Verify, capturar literalmente la solicitud original de OpenSpec/agente, operación, proyecto, ticket, rama/commit y cualquier **opción proporcionada por el workflow**. Distinguir información de pregunta o autorización reservada.

- Si OpenSpec entrega opciones explícitas: mostrarlas fielmente al operador y distinguirlas de cualquier explicación contextual. No inventar opciones atribuidas a OpenSpec.
- Si no entrega opciones: el agente de pensamiento contrasta la pregunta con ticket, specs y contexto canónico. Si existe respuesta inequívoca y está autorizado a darla, contestar mediante workflow nativo y reanudar sin interrumpir al operador.
- Si falta información/autoridad: presentar pregunta breve, causa, opciones razonables elaboradas POR EL AGENTE (etiquetadas como tales), consecuencias y recomendación fundamentada, o entrada libre cuando no haya alternativas.
- Las autorizaciones expresas humanas, cambios materiales de alcance, presupuesto excepcional, seguridad, políticas y merge de implementación NUNCA los resuelve el modelo por sí mismo.
- No perder artefactos, rama, progreso ni pregunta; reanudar desde checkpoint o continuación nativa válida; espera sin gastar cuota periódicamente; no repetir efectos externos confirmados.

La UI tendrá una sola bandeja de atención que responda qué se requiere, por qué, opciones y efecto. En móvil debe ser comprensible sin requerir operación completa. El gate humano muestra siempre la pregunta **vigente** con sus opciones; nunca una pregunta obsoleta sin opciones.

## 6. Persistencia y recuperación mínima

La fuente remota conserva tickets/comentarios; Git conserva ramas/commits; OpenSpec conserva especificaciones; proveedor Git conserva PR/merge. La DB conserva configuración de proyectos y agentes, referencias de ticket/branch/candidato, fase/operación pendiente, intentos y resultados mínimos, decisiones humanas, límites de gasto y datos indispensables para no duplicar acciones ni perder continuidad. No replica historia externa ni añade estados porque sí.

Fallos: preservar artefactos, mostrar causa; esperar capacidad sin quemar cuota; respaldo SOLO autorizado/compatible; corregir en ciclos acotados; recuperar tras reinicio; observar antes de repetir creaciones/comentarios/PR/merge. La re-ejecución de una etapa debe ser **idempotente**: observar el estado antes de repetir y no fallar porque el estado ya avanzó (p. ej., un cambio ya archivado no debe re-sincronizarse). Mantener protecciones de workspace, credenciales y permisos. NO nuevas sagas, scheduler ni motores de políticas sin un caso concreto que lo exija.

## 7. Reglas de ingeniería: POO, SOLID, DRY, KISS, YAGNI

- **SRP:** clase con una responsabilidad; el coordinador no acumula lógica Git, OpenSpec y UI.
- **OCP:** integrar un proveedor nuevo por contrato mínimo, sin reescribir núcleo.
- **LSP:** adaptadores verdaderamente sustituibles; capacidades declaradas deben funcionar.
- **ISP:** interfaces pequeñas específicas; no imponer métodos innecesarios.
- **DIP:** núcleo depende de contratos, no de proveedores concretos; inyección sencilla.
- **POO:** encapsular invariantes; composición frente a herencia sin relación real; polimorfismo útil, no patrones decorativos ni clases envoltorio.
- **DRY:** una única implementación/autoridad por regla, sin abstracciones universales prematuras.
- **KISS/YAGNI:** ninguna tabla, servicio, estado, motor, flag, check o dependencia sin requerimiento actual claro.

Por cada Change: censar consumidores; retirar lógica y pruebas obsoletas del alcance; pruebas enfocadas y E2E real para flujos de agentes; no presentar mocks o health 200 como prueba de valor; ninguna acumulación de compatibilidad muerta. Una versión con más código pero misma incapacidad funcional NO es progreso.

## 8. UI — evolución controlada

La composición/navegación aprobada prevalece frente a la UX histórica donde exista contradicción. Permanecen cinco pantallas/rutas independientes: Dashboard; Trabajo (acceso Dashboard); Trabajo actual (acceso Dashboard/Trabajo); Proyectos; Backlog (acceso Proyectos). No apilar las cinco pantallas en Home.

**Dashboard:** medidores analógicos de progreso del proyecto en foco, del Request/tarea actual y de cuota por modelo *solo con denominadores medidos*; gráfica de líneas de efectividad con tres dimensiones independientes (calidad/autonomía, tiempo efectivo/total/espera, tokens/costo por Request). Cuando faltan datos no mostrar porcentajes, límites ni gráficos inventados. Atención real y salud operativa compactas. Un proyecto configurado `ACTIVE` no implica que sea el ejecutor global ni que esté corriendo.

**Trabajo:** último terminado → en ejecución → siguiente. **Trabajo actual:** avances verificables por stage/tarea, resultados, agentes/modelos y tiempos reales; `HUMAN_REQUIRED` persistente, visible y respondible aquí, con Dashboard notificando y enlazando. **Proyectos:** lista+detalle, configuración y acceso a Backlog. **Backlog:** Pendiente/Terminado, FIFO y resultado autoritativos, formulario de Request con título, descripción y criterios de aceptación en lenguaje natural; operaciones visuales crear/editar/desactivar/reactivar/eliminar lógicamente.

**Frontera estricta:** toda funcionalidad cuya API/autoridad no exista se representa en la UI solo como control visual **deshabilitado con motivo claro**, sin confirmar mutaciones simuladas. En escritorio, centro de control legible; tablet operable por panel maestro/detalle; móvil con las cinco vistas enfocadas, observabilidad y decisiones humanas sencillas. Autenticación, permisos y reglas permanecen bajo backend; cliente sin Git/CLI/agentes/secretos. Sin cachear datos operativos autenticados ni métricas ficticias.

## 9. CI/CD y término de responsabilidad

mini me llega hasta PR de implementación fusionado, sync/archive nativos, PR documental fusionado y ticket cerrado. NO despliega ni verifica despliegue productivo: cada proyecto lo hace mediante CI/CD independiente. Sí exige pruebas pertinentes antes del merge y puede utilizar previews temporales para validar UI.

## 10. Autorización y alcance de cambios

No existe numeración de fases ni tabla fija de Issues. El trabajo se organiza en **cambios discretos**:

1. **Un Issue = un Change.** Cada cambio nace de un Issue abierto y corresponde a un único Change OpenSpec con alcance cohesivo. No se trocea un cambio en micro-Changes; tampoco se agrupan varios cambios independientes en uno.
2. **Autorización expresa del operador.** Ningún cambio se ejecuta sin que el operador lo haya autorizado. La autorización puede ser directa (el operador pide/admite el Issue) o por admisión FIFO del flujo autorizado.
3. **La corrección de un bloqueo del propio mini me es un cambio ordinario.** Reparar un flujo que impide ejecutar trabajo (apply, verify, sync/archive, gates) no es una "excepción": es un Issue y un Change como cualquier otro, con su propuesta, verificación, revisión y cierre.
4. **Alcance congelado por Issue.** El Change implementa exactamente el alcance del Issue; no añade funcionalidad no pedida ni "mejoras" colaterales (KISS/YAGNI, §7).
5. **Prioridad FIFO por admisión.** Cuando exista admisión autorizada, el orden es por fecha de creación ascendente con desempate estable por ID; el operador puede autorizar un Issue concreto fuera de orden de forma expresa.

Los Issues cerrados y los planes históricos no reviven como backlog activo salvo decisión expresa del operador.

## 11. Reconciliación del legado

Los planes 001–022, MM-R01–R10, N01–N05, expedientes, skills/harness y specs históricas son evidencia e historial técnico, **no una segunda cartera vigente** ni permiso para mantener flujos incompatibles. Solo un hallazgo auditado y pertinente puede trasladarse a un cambio autorizado. No borrar historial. Los Issues cerrados e históricos se tratan como historial de entrega, no como lista de autorización vigente. En toda contradicción con documentación anterior manda este contrato; en toda contradicción con código aún no migrado se describe la brecha, NO se considera la implementación conforme. La adopción de este contrato por GitHub no autoriza ejecutarlo sin Change OpenSpec y gates humanos.

## 12. Definición de éxito

mini me procesa un ticket remoto sin cola duplicada, hace propose, revisión independiente de propuesta, apply, verify y correcciones, revisión independiente de código cuando corresponda, PR con merge humano, sync/archive nativos con segundo PR autorizado, cierra ticket y elige siguiente; resuelve preguntas con contexto y eleva decisiones humanas sin perder trabajo. Una UI operable muestra ese ciclo. El operador autoriza cada cambio de forma expresa. La aplicación permanece pequeña, POO/SOLID/DRY, sin funcionalidades no autorizadas.

### Regla permanente de aceptación de entregas

Una implementación no se declara completa por el número de tareas marcadas, la cantidad de tests aprobados o el informe de su ejecutor. Todo criterio que exija una integración real necesita evidencia observable de la invocación, su resultado y sus efectos. Las pruebas simuladas no pueden presentarse como E2E reales. La revisión independiente debe contrastar el código y la evidencia contra un SHA inmutable. Ante evidencia ausente, ambigua o fallida, se aplica fail-closed.

**mini me debe ser una gacela, no un paquidermo: una aplicación pequeña, bien estructurada y capaz de entregar valor real.**
