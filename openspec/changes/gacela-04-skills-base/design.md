## Context

F2 ya concentra la identidad del proyecto, perfiles, catálogo observado, bootstrap Greenfield, worktrees, confinamiento, GitHub y continuidad. F3 añade el coordinador del ciclo OpenSpec, la skill mínima para preparar PR y las reglas de revisión, merge, Sync, Archive y cierre. El repositorio también contiene skills oficiales de OpenSpec y material histórico de harnesses; ese material no es una segunda autoridad.

El cambio debe hacer utilizables las capacidades mínimas de F4 sin convertirlas en un nuevo motor de plugins, catálogo, validación o instalación. La instalación ocurre únicamente en Greenfield y el runtime de mini me mantiene sus propias protecciones fuera del repositorio del proyecto.

## Goals / Non-Goals

**Goals:**

- Reutilizar las integraciones de F2/F3 para normalización Gherkin, comunicación, PR, bootstrap y preflight.
- Hacer explícita una selección pequeña de capacidades por perfil y una instalación Greenfield idempotente, verificable y no destructiva.
- Facilitar contexto, investigación, ingeniería, pruebas y revisión sin introducir gates adicionales.
- Probar el valor con un recorrido E2E automatizado y retirar únicamente código que el censo de consumidores demuestre sustituido.
- Mantener trazabilidad de la fuente original, criterios, identidad del candidato, permisos, gasto y decisiones humanas.

**Non-Goals:**

- No Brownfield, ADO, framework de plugins, router universal, motor de calidad, clasificador de riesgo, segundo scheduler ni cola.
- No se modifica la semántica ni la generación de proposal, design, specs, tasks, Validate, Verify, Sync o Archive de OpenSpec.
- No se duplica el catálogo de agentes, `minime-pr-preparer`, la autoridad GitHub, el coordinador F3, el confinamiento, los guards ni el control de cuotas.
- No se despliega, migra PostgreSQL productivo, activa scheduler, consume modelos durante Propose ni implementa F5.

## Decisions

### REUSE: autoridades y adaptadores existentes

- `ProjectCatalogService`, perfiles/conexiones de F2 y el bootstrap Greenfield siguen siendo la fuente de capacidades, identidad y preparación.
- `OpenSpecAdapter` y la resolución de workflows siguen delegando en la instalación oficial; el paquete de F4 solo declara y enlaza skills ya instaladas.
- `GitHubAdapter` y su contrato de tickets/PR publican Issue, comentarios y PR; el coordinador F3 conserva merge, cierre, idempotencia y decisiones humanas.
- Worktree/repository guards, confinamiento, preflight CLI, autenticación, capacidad y evidencia existentes protegen el runtime; no se copian al proyecto ni se reemplazan por hooks.
- Las skills oficiales `openspec-*`, `minime-pr-preparer` y los guards ya instalados se reutilizan por referencia. No se crea otra versión de sus instrucciones.

### ADAPT: contratos pequeños en sus propietarios

- Adaptar el flujo de preparación Greenfield para resolver un manifest de capacidades por perfil desde el catálogo observado, instalar solo recursos compatibles y verificar disponibilidad ligera en reanudaciones.
- Adaptar la preparación de contexto del agente para incluir Request, comentarios, adjuntos, decisiones y referencias canónicas sin copias divergentes.
- Adaptar el contenido semántico de las skills de comunicación/PR, mientras el adaptador GitHub solo consulta y publica de forma determinista, con español sencillo, enlaces verificables, ausencia de secretos y deduplicación remota.
- Mantener los PR de implementación y documental dentro de la integración mínima de F3; F4 no decide complejidad, revisión, merge o cierre.

### ADAPT: skills existentes en ambas instalaciones

- Adaptar `.agents/skills/minime-engineering-discipline/SKILL.md` y `.agent/skills/minime-engineering-discipline/SKILL.md` para que orienten arquitectura definida por el contexto, código comprensible y pruebas proporcionales, sin exigir intervención en artefactos OpenSpec, postdeploy obligatorio o reglas heredadas que no correspondan.
- Adaptar `.agents/skills/minime-real-e2e-proof/SKILL.md` y `.agent/skills/minime-real-e2e-proof/SKILL.md` para distinguir evidencia técnica, E2E real y verificación desplegada; F4 exige E2E real cuando corresponda, pero no despliegue ni postdeploy. Sin capacidad o autorización, el resultado es `NOT_VERIFIED`/`WAITING_CAPACITY`, nunca PASS ni HUMAN REQUIRED por un fallo técnico.
- Adaptar `.agents/skills/minime-safe-retirement/SKILL.md` y `.agent/skills/minime-safe-retirement/SKILL.md` para retirar solo consumidores demostrados como obsoletos, usar una nota de evidencia proporcional cuando aplique y no exigir un Removal Ledger universal, postdeploy o referencias R01–R10.
- Mantener ambas copias coherentes y con la misma procedencia; no crear un tercer espejo ni convertir estas skills en gates ejecutables.

### CREATE: solo lo que el contrato de F4 exige

- Un manifest/catalogación mínima de capacidades concretas que pueda seleccionar cada perfil y que registre procedencia, compatibilidad y estado observable.
- Enlaces o entradas de skills de asistencia para contexto, disciplina de ingeniería, E2E y retiro seguro cuando no exista una capacidad equivalente reutilizable.
- Casos de prueba y evidencia determinista/real que cubran instalación Greenfield, no sobrescritura, disponibilidad, Request Gherkin, comunicación, PR y retiro.

No se crean comandos OpenSpec, generadores Markdown, verificadores semánticos ni un sistema de instalación paralelo. El agente, mediante su skill, produce el contenido Gherkin, comentarios y PR; `GitHubAdapter` ejecuta únicamente lecturas/publicaciones deterministas con seguridad e idempotencia. No se genera texto semántico por plantillas dentro del adaptador ni se duplica `minime-pr-preparer`. Si el inventario demuestra que una capacidad ya existe, se conserva como REUSE y no se crea un duplicado.

### Seguridad, continuidad y autoridad

La instalación se ejecuta en el workspace Greenfield ya vinculado y solo después de verificar repositorio, identidad, branch base, proveedor, permisos, capacidad y confinamiento. Cada recurso se valida por nombre/procedencia/hash o contrato observable antes de usarse; un conflicto queda preservado para la recuperación existente. Brownfield no se modifica.

Los comentarios y PR se publican únicamente mediante GitHub y con candidato/Issue exactos. Las decisiones humanas, el gasto, los merges y el cierre remoto no se autoconceden. Los fallos conservan candidato, fuentes y checkpoint y no disparan reintentos pagados implícitos. El agente investiga y resuelve primero; `HUMAN REQUIRED` queda reservado a una decisión material no resoluble o a una autorización humana, mientras fallos de capacidad, seguridad, autenticación, cuota o herramienta siguen las rutas técnicas de preflight y recuperación.

### Pruebas y retiro

El recorrido de aceptación usa un Issue de prueba controlado y un fixture Greenfield desechable, agentes reales solo cuando Apply/E2E esté autorizado, y pruebas locales deterministas para errores, idempotencia y seguridad. Mocks pueden probar contratos aislados, pero no se presentan como E2E. Un censo de callers, configuración y dependencias precede cualquier retiro; datos históricos y compatibilidad legítima se conservan.

### Cobertura de aceptación del Issue #172

El Apply debe registrar una matriz de evidencia, no repetir escenarios en las specs. Los 35 criterios quedan cubiertos así: S01 (`S01_AC01`–`S01_AC05`) por `request-normalization-and-communication` y tareas 2.1–2.6; S02 (`S02_AC01`–`S02_AC02`) por la misma spec y tareas 2.3–2.4; S03 (`S03_AC01`–`S03_AC02`) por la misma spec y tarea 2.5; S05 (`S05_AC01`–`S05_AC03`) por `delivery-quality-and-safe-retirement` y tareas 4.2–4.3; S06 (`S06_AC01`–`S06_AC03`) por esa spec y tareas 5.1–5.4; S07 (`S07_AC01`–`S07_AC02`) por esa spec y tareas 5.5–5.7; GF (`GF_AC01`–`GF_AC05`) por `greenfield-agent-capability-bootstrap` y tareas 3.1–3.6; HA (`HA01_AC01`–`HA04_AC01`) por tareas 4.1–4.5; H (`H01_AC01`–`H03_AC01`) por tareas 3.5, 4.3 y 4.5; F3 (`F3_AC01`–`F3_AC04`) por tareas 2.4–2.5, 3.5 y 4.3–4.4; DONE (`DONE_AC01`–`DONE_AC02`) por tareas 5.4 y 6.1–6.6. La ausencia de autorización o capacidad real se registra como no verificada, nunca como PASS.

## Risks / Trade-offs

- **[Capacidad instalada cambia entre preflight y uso]** → conservar snapshot de capacidades, volver a comprobar lo indispensable antes de invocar y bloquear de forma explicable sin gastar cuota.
- **[Archivo o configuración existente entra en conflicto]** → no sobrescribir; guardar el candidato y usar la recuperación/idempotencia ya existente.
- **[Skills históricas contradicen el contrato]** → tratarlas como referencia, enlazar solo las compatibles y retirar duplicados únicamente con consumidores demostrados.
- **[E2E de proveedor no autorizado]** → marcar evidencia como no verificada y completar pruebas locales; no convertir un mock en PASS ni activar un fallback.
- **[La normalización remota encuentra una edición concurrente]** → comparar versión/actualización, rebasar de forma segura y evitar comentarios o cierres duplicados.

## Migration Plan

1. Durante Apply, confirmar inventario y consumidores; crear/adaptar solo manifest, enlaces y propietarios existentes, sin cambiar runtime productivo.
2. Instalar y verificar capacidades en el bootstrap de un fixture Greenfield aislado; probar reanudación y conflicto sin sobreescritura.
3. Ejecutar el recorrido de Request, comentarios y ambos PR con evidencia de proveedor, y ejecutar regresión, Validate/Verify oficiales y `git diff --check`.
4. Retirar rutas sustituidas únicamente tras el censo y las pruebas; mantener una migración/rollback conservadora si se toca estado durable.
5. Publicar el PR de implementación, esperar la autoridad de merge de F3, y después preparar el PR documental con Sync/Archive nativos. F4 no despliega ni modifica producción.

## Open Questions

No hay decisiones materiales pendientes para Propose. La disponibilidad concreta de una skill o workflow se resolverá durante Apply mediante el catálogo real; una ausencia, fallo de capacidad, seguridad o cuota se conserva como bloqueo técnico y sigue la recuperación existente. Solo una decisión material no resoluble o una autorización humana reservada usa `HUMAN REQUIRED`.
