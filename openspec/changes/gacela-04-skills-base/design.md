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
- Adaptar las plantillas/serializadores de comunicación y PR del adaptador existente para español sencillo, enlaces verificables, ausencia de secretos y deduplicación remota.
- Mantener los PR de implementación y documental dentro de la integración mínima de F3; F4 no decide complejidad, revisión, merge o cierre.

### CREATE: solo lo que el contrato de F4 exige

- Un manifest/catalogación mínima de capacidades concretas que pueda seleccionar cada perfil y que registre procedencia, compatibilidad y estado observable.
- Enlaces o entradas de skills de asistencia para contexto, disciplina de ingeniería, E2E y retiro seguro cuando no exista una capacidad equivalente reutilizable.
- Casos de prueba y evidencia determinista/real que cubran instalación Greenfield, no sobrescritura, disponibilidad, Request Gherkin, comunicación, PR y retiro.

No se crean comandos OpenSpec, generadores Markdown, verificadores semánticos ni un sistema de instalación paralelo. Si el inventario demuestra que una capacidad ya existe, se conserva como REUSE y no se crea un duplicado.

### Seguridad, continuidad y autoridad

La instalación se ejecuta en el workspace Greenfield ya vinculado y solo después de verificar repositorio, identidad, branch base, proveedor, permisos, capacidad y confinamiento. Cada recurso se valida por nombre/procedencia/hash o contrato observable antes de usarse; un conflicto queda preservado para la recuperación existente. Brownfield no se modifica.

Los comentarios y PR se publican únicamente mediante GitHub y con candidato/Issue exactos. Las decisiones humanas, el gasto, los merges y el cierre remoto no se autoconceden. Los fallos conservan candidato, fuentes y checkpoint y no disparan reintentos pagados implícitos.

### Pruebas y retiro

El recorrido de aceptación usa un fixture Greenfield desechable, agentes reales solo cuando Apply/E2E esté autorizado, y pruebas locales deterministas para errores, idempotencia y seguridad. Mocks pueden probar contratos aislados, pero no se presentan como E2E. Un censo de callers, configuración y dependencias precede cualquier retiro; datos históricos y compatibilidad legítima se conservan.

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

No hay decisiones materiales pendientes para Propose. La disponibilidad concreta de una skill o workflow se resolverá durante Apply mediante el catálogo real; si una capacidad imprescindible no existe, se conservará el bloqueo técnico y se usará únicamente la ruta autorizada de HUMAN REQUIRED.
