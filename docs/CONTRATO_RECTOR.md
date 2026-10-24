# mini me — Contrato rector de producto y arquitectura

**Versión 1.2 — 21 de octubre de 2026.**
**Autoridad:** este documento es la dirección funcional y arquitectónica de mini me; sustituye las decisiones incompatibles de planes, specs, fichas y contratos históricos. La implementación existente NO se considera conforme por la sola publicación de este documento.
**Naturaleza:** instalación personal única, no producto comercial. Plan de reconstrucción de **exactamente seis fases, un Change OpenSpec por fase**, con una o varias specs dentro de cada Change.
**Estado:** contrato propuesto en PR; su aprobación no autoriza despliegues, migraciones, reinicio de scheduler, consumo de agentes ni merge de PR ajenos.

## 1. La gacela, no el paquidermo

mini me debe ser una aplicación pequeña, rápida, mantenible, extensible y, sobre todo, útil. Coordina agentes para convertir requerimientos externos en implementaciones verificadas, revisadas, fusionadas y archivadas mediante los workflows oficiales de OpenSpec. No programa ni razona en lugar de los agentes.

Principios no negociables: simplicidad; reutilización antes de crear; una responsabilidad por componente; configuración antes que valores hardcodeados; POO bien aplicada, SOLID y DRY; KISS y YAGNI; autonomía que evite al operador ser mensajero; observabilidad clara; E2E real; reducción activa de código, dependencias, estados y tablas sin utilidad. Entre soluciones equivalentes se adopta la más sencilla que preserva la seguridad y calidad.

**Prohibición:** mini me NO genera mediante plantillas propias proposal/design/specs/tasks, NO reimplementa propose/update/continue/apply/verify/sync/archive, NO fusiona Markdown o mueve directorios como sustituto del workflow OpenSpec, NO crea motores de razonamiento, ranking, clasificación o revisión propios, NO duplica la fuente de tickets en PostgreSQL y NO administra despliegues productivos. Puede leer artefactos, verificar resultados observables, proteger repositorios, controlar permisos/costos y coordinar Git.

## 2. Responsabilidades y fronteras

- **Proveedor de tickets:** fuente autoritativa de requerimientos, fechas, comentarios y cierre; GitHub Issues inicialmente.
- **Git y proveedor de PR:** repositorios, ramas, worktrees, commits, diffs, PR y merges.
- **OpenSpec:** autoridad de comportamiento/diseño/tareas y de los workflows nativos usados por agentes.
- **Agentes:** pensamiento/propuesta/verify, ejecución/apply/correcciones, revisión independiente de solo lectura y respaldo compatible.
- **mini me:** configura proyectos, identifica y selecciona tickets, prepara worktrees, invoca agentes con skills oficiales, recibe evidencias, publica comentarios/PR, presenta decisiones, ejecuta operaciones Git autorizadas y reanuda trabajo. No produce contenido semántico OpenSpec ni código.
- **PostgreSQL:** configuración y mínimo estado operativo necesario para continuidad/idempotencia, autorizaciones y límites de gasto. Nunca es el backlog maestro.
- **CI/CD propio del proyecto:** todo despliegue productivo, fuera del alcance de mini me.

Una única API FastAPI, modular y con la UI consumiéndola. No segunda API ni microservicios.

## 3. Módulo de proyectos

Cada proyecto configura: nombre/id; repositorio y rama base (main por defecto); origen de tickets; ubicación/contexto OpenSpec; agente y modelo de pensamiento, ejecución, revisión independiente y respaldo; capacidad compatible con CLI/workflows por rol; skills existentes; esfuerzo; límite de correcciones; política sencilla de revisión de código; política de costo y estado activo/pausado.

**Contratos distintos para fuente de tickets y proveedor Git/PR** (pueden diferir). Fuente de tickets intercambiable mediante una interfaz mínima para listar/leer/crear/comentar/cerrar, pero SOLO GitHub se implementa inicialmente. NO construir ADO ni framework de plugins hasta existir necesidad.

Esfuerzo por defecto medio para propone/updates sustantivos, apply, verify y revisión; mínimo compatible para sync/archive. Estas asignaciones no autorizan optimizadores o escaladores automáticos. El respaldo necesita capacidad real del workflow y autorización de gasto; un API de texto no se considera CLI de edición de archivos. La identidad del autor de un candidato no puede certificar su propia revisión.

Al configurar contexto, reutilizar e instalar skills OpenSpec preexistentes; usar AGENTS.md y equivalentes específicos de agente para enlazar al contexto canónico, sin mantener copias divergentes, sobrescribir instrucciones existentes ni escribir en main sin la ruta Git autorizada. Skills de tickets/comentarios/PR/cierre **preexistentes o reutilizables**, seleccionadas por proyecto; la fase 4 solo crea las capacidades base que falten y no dupliquen servicios externos ni OpenSpec.

## 4. Flujo OpenSpec (una unidad de trabajo activa por proyecto)

Al activar proyecto: consultar directamente tickets abiertos y elegibles en el origen remoto; orden ascendente por fecha de creación, desempate estable por ID; comenzar el más antiguo. No mantener cola duplicada ni usar scoring, envejecimiento, prioridades sintéticas o roadmap como orden alternativo. Si el ticket seleccionado queda bloqueado, conservarlo; no saltar silenciosamente a otro. El siguiente empieza cuando se haya completado el cierre documental y del ticket anterior.

**Explore (pensamiento):** indagar de forma autónoma el contexto del ticket, repositorio y archivos de diseño. Emitir READY TO PROPOSE si hay suficiente información, o pausar con HUMAN REQUIRED con opciones estructuradas en español si existe ambigüedad material irresoluble.

**Propose (pensamiento):** invocar workflow nativo de propuesta, obtener artefactos (`proposal.md`, `specs/`, `design.md`, `tasks.md`), ejecutar validación estricta CLI con autocorrección. Evaluar complejidad fundamentada (`low`, `moderate`, `high`). Para complejidad alta, invocar revisión independiente de solo lectura; para complejidad baja/moderada, avanzar directamente a Apply.

**Apply (ejecutor):** verificar previamente que el ejecutor dispone de Verify nativo instalado (bloqueo *fail-closed* si falta); ejecutar workflow nativo apply, diseñar y ejecutar obligatoriamente pruebas unitarias/E2E reales en el proyecto (exit code 0), implementar tareas de `tasks.md` y pasar a Verify.

**Verify (ejecutor):** ejecutado por el mismo agente ejecutor mediante el workflow oficial OpenSpec Verify (y NO por el agente de pensamiento). Ante discrepancias, bucle de autocorrección con Apply. Al aprobar: baja/moderada pasa a preparación de PR; alta complejidad pasa a revisión independiente de código de solo lectura.

**Revisión independiente de código (condicional para alta complejidad):** agente de solo lectura contrasta ticket, propuesta, specs, diff y pruebas. Hallazgos → vuelta a Apply/Verify. Aprobación → preparación de PR.

**Preparación de PR y política de merge:** F3 entrega la skill mínima `minime-pr-preparer` con referencias estrictamente informativas (`Addresses #...` o `Ref #...`) excluyendo taxativamente palabras de cierre automático (`Fixes`, `Closes`, `Resolves`).
- *Primer PR (implementación):* merge automático por mini me para baja/moderada; acuse informativo humano («Estoy enterado») para alta complejidad antes de que mini me ejecute el merge.
- *Rama documental y segundo PR:* tras confirmar merge de PR1, crear rama fresca `doc-close-<num>-<slug>` desde `main` actualizado en la raíz administrada; agente de pensamiento ejecuta Sync y Archive nativos; PR2 documental con merge automático incondicional por mini me.
- *Cierre remoto:* mini me cierra el Issue remoto únicamente tras verificar el merge de PR2, liberando el bloqueo y pasando al siguiente ticket FIFO.

## 5. Intervención humana asistida

En Propose, Apply y Verify, capturar literalmente la solicitud original de OpenSpec/agente, operación, proyecto, ticket, rama/commit y cualquier **opción proporcionada por el workflow**. Distinguir información de pregunta o autorización reservada.

- Si OpenSpec entrega opciones explícitas: mostrarlas fielmente al operador y distinguirlas de cualquier explicación contextual. No inventar opciones atribuidas a OpenSpec.
- Si no entrega opciones: el agente de pensamiento contrasta la pregunta con ticket, specs y contexto canónico. Si existe respuesta inequívoca y está autorizado a darla, contestar mediante workflow nativo y reanudar sin interrumpir al operador.
- Si falta información/autoridad: presentar pregunta breve, causa, opciones razonables elaboradas POR EL AGENTE (etiquetadas como tales), consecuencias y recomendación fundamentada, o entrada libre cuando no haya alternativas.
- Las autorizaciones expresas humanas, cambios materiales de alcance, presupuesto excepcional, seguridad, políticas y merge de implementación NUNCA los resuelve el modelo por sí mismo.
- No perder artefactos, rama, progreso ni pregunta; reanudar desde checkpoint o continuación nativa válida; espera sin gastar cuota periódicamente; no repetir efectos externos confirmados.

La UI tendrá una sola bandeja de atención que responda qué se requiere, por qué, opciones y efecto. En móvil debe ser comprensible sin requerir operación completa.

## 6. Persistencia y recuperación mínima

La fuente remota conserva tickets/comentarios; Git conserva ramas/commits; OpenSpec conserva especificaciones; proveedor Git conserva PR/merge. La DB conserva configuración de proyectos y agentes, referencias de ticket/branch/candidato, fase/operación pendiente, intentos y resultados mínimos, decisiones humanas, límites de gasto y datos indispensables para no duplicar acciones ni perder continuidad. No replica historia externa ni añade estados porque sí.

Fallos: preservar artefactos, mostrar causa; esperar capacidad sin quemar cuota; respaldo SOLO autorizado/compatible; corregir en ciclos acotados; recuperar tras reinicio; observar antes de repetir creaciones/comentarios/PR/merge. Mantener protecciones de workspace, credenciales y permisos. NO nuevas sagas, scheduler ni motores de políticas sin un caso concreto que lo exija.

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

## 8. UI (se mantienen los criterios previamente acordados)

Español, densidad informativa útil, jerarquía clara, uso consciente del espacio, componentes coherentes. **Mobile** observa qué hace/terminó/sigue y permite atender preguntas sencillas; **Tablet** permite operar con master-detail/drawers; **Web** es centro de control con paneles redimensionables/colapsables y persistencia de layout cuando útil. Ver ticket, etapa, agentes, pruebas, revisión, preguntas con opciones originales vs propuestas, autorizaciones, PR, bloqueos y cierre. Diseño de calidad desde primer prototipo; no construir UI alrededor de estados accidentales de la implementación.

## 9. CI/CD y término de responsabilidad

mini me llega hasta PR de implementación fusionado, sync/archive nativos, PR documental fusionado y ticket cerrado. NO despliega ni verifica despliegue productivo: cada proyecto lo hace mediante CI/CD independiente. Sí exige pruebas pertinentes antes del merge y puede utilizar previews temporales para validar UI.

## 10. Plan obligatorio: EXACTAMENTE seis fases

Una fase = **un Change OpenSpec**, que puede contener una o varias especificaciones; tareas de migración, limpieza, pruebas y documentación permanecen dentro de ese Change. No trocear en micro-Changes. No comenzar siguiente fase hasta cierre de la anterior. La actualización de contexto/backlog NO crea ni activa los seis Changes. Los Change slugs son identificadores planeados, no pruebas de creación.

| Fase | Issue | Change planificado | Entrega |
| --- | --- | --- | --- |
| 1 | [#169](https://github.com/silverberdi/mini-me/issues/169) | gacela-01-depuracion-inicial | Eliminar emulaciones OpenSpec, lógica y DB obsoletas de forma segura |
| 2 | [#170](https://github.com/silverberdi/mini-me/issues/170) | gacela-02-proyectos | Proyectos, contextos, roles/modelos, GitHub como origen inicial |
| 3 | [#171](https://github.com/silverberdi/mini-me/issues/171) | gacela-03-openspec-y-revision | Flujo OpenSpec real, revisión, atención humana, merges y cierre |
| 4 | [#172](https://github.com/silverberdi/mini-me/issues/172) | gacela-04-skills-base | Catálogo mínimo de skills existentes/complementos faltantes |
| 5 | [#173](https://github.com/silverberdi/mini-me/issues/173) | gacela-05-ui-self-hosted | UI web/tablet/mobile ejecutada por **mini me** sobre sí mismo |
| 6 | [#174](https://github.com/silverberdi/mini-me/issues/174) | gacela-06-depuracion-final | Eliminar código y DB obsoletos restantes, ejecutado por **mini me** |

### Fase 1 — Depuración inicial

Auditar de verdad código/consumidores/writers/tests/tablas y retirar implementaciones propias de propose/verify semántico/sync/archive, prompt-emulaciones y estado de operaciones heredadas sin utilidad. Preservar API, autenticación, integración Git, seguridad y continuidad mínimas. Migrar DB con Alembic, preservando datos necesarios y plan de reversión; no borrar indiscriminadamente. Probar el núcleo restante. No fingir que fase 1 ya entrega workflow end-to-end de fase 3.

### Fase 2 — Proyectos

Registrar, editar, activar/pausar; adaptar tickets con GitHub únicamente (contrato extensible para ADO sin implementarlo), Git/PR separado; roles de pensamiento/ejecución/revisión/respaldo configurables; esfuerzo/capacidades, política de revisión, límites y gasto, contexto OpenSpec referenciado por instrucciones del agente; selección de skills existentes. No crear skills de fase 4 ni AI router universal.

### Fase 3 — OpenSpec y revisión independiente

Primera entrega funcional de un ticket real al cierre: seleccionar más antiguo; propose/revisión propuesta; apply; verify/correcciones; revisión de código condicional; PR y merge humano; rama nueva de sync/archive nativos; PR documental y merge autorizado; cierre issue y siguiente. Manejar preguntas humanas contextualizadas y reanudación. E2E real de CLIs/workflows, Git, proveedor remoto, sin simular IA. Puede operarse mediante CLI/API mínima existente; NO requiere UI fase 5.

### Fase 4 — Skills base

Inventario, selección, vinculación y, SOLO si faltan, construcción de skills reutilizables concretas para ticket detallado, comentarios por etapa, PR y cierre. Mantener nativos OpenSpec intactos; no duplicar por proyecto, no ADO ni framework universal. La funcionalidad básica de integración GitHub para demostrar F3 puede ser determinista antes de esta fase.

### Fase 5 — UI, primera ejecución por mini me

UI española con las tres modalidades, proyectos/roles, progreso, bandeja humana, opciones y merge autorizado. **mini me debe coordinar y ejecutar su propio Change F5**, con agentes reales, propuesta/verify/revisión, PR, autorización humana, sync/archive y cierre. Se opera desde CLI/API existente hasta que la UI funcione; el desarrollo no depende circularmente de la UI terminada. Prueba E2E navegador y autonomía real, no transferencia manual de prompts.

### Fase 6 — Redepuración final por mini me

Segunda limpieza de código muerto, consumidores, interfaces, dependencias, tests y DB obsoletos tras fases previas. Alembic seguro, preservación de datos y pruebas de regresión/E2E. NO introducir funcionalidades. **mini me debe coordinar y ejecutar su propio Change F6** hasta cierre documental y de ticket. La limpieza final no se limita a números de líneas: responsabilidades claras y operación real.

Criterio común de cierre: cumplimiento funcional, pruebas pertinentes reales, PR de implementación revisado y merge humano, sync/archive nativos, PR documental fusionado y ticket cerrado (respetando la transición desde la infraestructura existente en F1–F2). Las fases 5–6 añaden **prueba material de autoejecución**. El usuario no es mensajero entre agentes. No habilitar scheduler ni gastar cuota al aprobar documentos.

## 11. Reconciliación del legado

Los planes 001–022, MM-R01–R10, N01–N05, expedientes, skills/harness y specs históricas son evidencia e historial técnico, **no una segunda cartera vigente** ni permiso para mantener flujos incompatibles. Solo un hallazgo auditado y pertinente puede trasladarse a una de las seis fases. No borrar historial. Los nueve Issues antiguos abiertos (#15, #57, #133–#138, #162) fueron revisados y cerrados individualmente como trabajo no planificado por separado o duplicado, dejando comentario y preservando la información; solo #169–#174 permanecen abiertos. Se cerraron SIN MERGE los PR #140 (motor de quality hooks) y #152 (continuación auth del orquestador heredado), también con comentarios; se conservan como evidencia histórica, no como código autorizado para incorporar automáticamente. El único PR abierto es #175, el presente contrato. Los requisitos UX de #162 siguen como entrada de F5 y sus conflictos deben resolverse explícitamente; ver docs/RECONCILIACION_LEGADO.md.

En toda contradicción con documentación anterior manda este contrato; en toda contradicción con código aún no migrado se describe la brecha, NO se considera la implementación conforme. La adopción de este contrato por GitHub no autoriza ejecutarlo sin Change OpenSpec y gates humanos.

## 12. Definición de éxito

mini me procesa un ticket remoto sin cola duplicada, hace propose, revisión independiente de propuesta, apply, verify y correcciones, revisión independiente de código cuando corresponda, PR con merge humano, sync/archive nativos con segundo PR autorizado, cierra ticket y elige siguiente; resuelve preguntas con contexto y eleva decisiones humanas sin perder trabajo. Una UI operable muestra ese ciclo. F5 y F6 son ejecutadas por mini me. La aplicación final es pequeña, POO/SOLID/DRY, sin código/DB heredados superfluos.

**mini me debe ser una gacela, no un paquidermo: una aplicación pequeña, bien estructurada y capaz de entregar valor real.**
