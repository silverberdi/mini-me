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

**Propose (pensamiento):** actualizar base, crear una rama/worktree para el ticket, invocar skill nativa de propuesta, obtener artefactos del esquema, commit. Revisor independiente de solo lectura contrasta ticket/contexto/propuesta; si hay observaciones, publicar comentario y ejecutar update nativo con pensamiento, nuevo commit y nueva revisión, hasta aprobar o llegar al límite. Tras aprobar, pasar la MISMA rama a Apply.

**Apply (ejecutor):** entrar al worktree recibido, invocar skill nativa apply, implementar y probar conforme a OpenSpec, registrar cambios y commit; pasar rama a Verify.

**Verify (pensamiento):** ejecutar workflow nativo verify, contrastar especificaciones y pruebas; fallos concretos se comentan y vuelven al ejecutor usando workflow nativo de corrección; repetir verify con límite de intentos. Al aprobar, decidir si la revisión independiente de código es obligatoria según política sencilla del proyecto y justificar decisión (sin motor de riesgo). Si no, mini me hace push y PR.

**Revisión independiente de código (condicional):** agente distinto y de solo lectura contrasta ticket, propuesta aprobada, specs, diff y pruebas contra commit preciso. Hallazgos → comentario, Apply, Verify, nueva revisión. Aprobación → mini me publica commit/push/PR sin convertir al revisor en autor. Cualquier modificación posterior requiere revalidar aprobaciones del candidato.

**Merge humano:** PR muestra requerimiento, propuesta, verificación y revisión; operador autoriza desde UI, ligado al PR y SHA efectivamente revisados. mini me realiza merge por adaptador Git bajo protección de rama. Nadie puede autorizar su propio merge de implementación.

**Sync/Archive (pensamiento, menor esfuerzo compatible):** tras comprobar merge humano, crear OTRA rama de cierre desde main actualizado. Agente usa workflows nativos sync y archive. mini me crea commit/push/PR exclusivamente documental y puede realizar su merge **solo cuando esté autorizado por este contrato y por las protecciones reales del repositorio**; confirmar merge, cerrar ticket remoto, iniciar siguiente ticket. Si el segundo merge no está permitido, solicitar humano; no declarar cierre ficticio.

Las revisiones de propuesta siempre son independientes; la revisión de código es condicional. Todas las vueltas de corrección tienen un límite de intentos configurable. Ninguna revisión puede mutar su propio objeto de evaluación.

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

Los planes 001–022, MM-R01–R10, N01–N05, expedientes, skills/harness y specs históricas son evidencia e historial técnico, **no una segunda cartera vigente** ni permiso para mantener flujos incompatibles. Solo un hallazgo auditado y pertinente puede trasladarse a una de las seis fases. No borrar ni cerrar masivamente historiales sin revisión; ver docs/RECONCILIACION_LEGADO.md.

En toda contradicción con documentación anterior manda este contrato; en toda contradicción con código aún no migrado se describe la brecha, NO se considera la implementación conforme. La adopción de este contrato por GitHub no autoriza ejecutarlo sin Change OpenSpec y gates humanos.

## 12. Definición de éxito

mini me procesa un ticket remoto sin cola duplicada, hace propose, revisión independiente de propuesta, apply, verify y correcciones, revisión independiente de código cuando corresponda, PR con merge humano, sync/archive nativos con segundo PR autorizado, cierra ticket y elige siguiente; resuelve preguntas con contexto y eleva decisiones humanas sin perder trabajo. Una UI operable muestra ese ciclo. F5 y F6 son ejecutadas por mini me. La aplicación final es pequeña, POO/SOLID/DRY, sin código/DB heredados superfluos.

**mini me debe ser una gacela, no un paquidermo: una aplicación pequeña, bien estructurada y capaz de entregar valor real.**
