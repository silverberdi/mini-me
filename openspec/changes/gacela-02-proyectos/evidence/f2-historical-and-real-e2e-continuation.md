# F2 — Continuidad histórica y preparación del E2E real

Fecha: 2026-10-23. Documento de ejecución para el **mismo Change**
`gacela-02-proyectos` y PR #178. Este archivo **no** demuestra la aceptación:
es el contrato de preflight, evidencia exigida y prohibiciones para los cuatro
ítems aún pendientes. No constituye autorización autónoma de gasto ni de
migraciones productivas.

## Estado verificable antes de esta continuación

- Candidato determinista: commit `8ed15fe385dce88ea85592451b19104c2ce2dc99`.
  `38 passed` focalizadas; regresión `745 passed, 13 skipped, 2 warnings`;
  Ruff, OpenSpec strict y Git diff PASS. El E2E de prueba simula agente y PR
  en Git local; **no** sustituye a GitHub, agente real ni merge humano.
- El catálogo F2 está fijo: 20 secciones, 204 documentos opcionales,
  índice solo de documentos poblados, distribución múltiple permitida y ZIP
  original inmutable. No hay backlog operativo generado.
- La última inspección operativa autorizada (2026-10-22) fue **solo lectura**:
  Alembic `r02_contract_review_budget_identity`, sin columnas F2; filas
  `mini-me` y `mini-me-fixture` en `READY_FOR_WORK` antiguo. Sus
  repositorios administrados estaban en `main` pero dirty; los bindings
  coincidían con sus respectivos remotos. No hay prueba de readiness F2.
- `f2_project_configuration` migra históricamente
  `READY_FOR_WORK -> CONFIGURED` y preserva el estado/reason anterior
  en `onboarding_checkpoint`; **no** inventa perfiles ni `PREPARED`.
  Las migraciones han pasado pruebas de PostgreSQL desechable, no
  aplicación productiva.
- Repositorio privado E2E:
  `silverberdi/mini-me-f2-e2e-20261023`; usar solo ese repositorio
  desechable tras verificar GitHub App y el `main`/SHA vinculados.
  El proyecto/operación anterior `f2-e2e-gacela-20261023e` está
  BLOCKED; su último intento de Codex terminó exit 0 con uso observado
  (163590 input, 3348 output) pero no publicó PR al fallar scope.
  El candidato fue susceptible de limpieza antes de las correcciones de
  cuarentena. Su existencia actual es **DESCONOCIDA** hasta inspección
  explícita; no afirmar recuperación ni solicitar nueva ejecución por defecto.
  La concesión incremental permanece reservada.
- **GitHub preflight externo de solo lectura (2026-10-23):** el repositorio
  desechable `silverberdi/mini-me-f2-e2e-20261023` presenta únicamente la
  rama `main`; la búsqueda de PR de bootstrap no devolvió resultados.
  Esto no certifica inexistencia de worktree/candidato local ni permisos
  de la GitHub App, que deben verificarse en el host antes de cualquier
  operación pagada.

## Secuencia obligatoria — ejecutar con OpenSpec Apply, sin abrir Change ni PR nuevo

### A. Gate sin inferencia: 7.1b / continuidad de filas históricas

1. Verificar la rama y el SHA actual del PR #178 y el estado limpio del
   checkout de trabajo; no asumir que el checkout operativo (dirty) es
   reemplazable, no hacer `git reset --hard`, borrar worktrees ni tocar
   `main`. Operar en checkout aislado y sin mutar repos productivos.
2. Con lectura de la BD operativa bajo transacción READ ONLY y sin imprimir
   secretos, observar Alembic, esquema, exactamente los registros `mini-me`
   y `mini-me-fixture`, repository/base branch, roles legacy,
   configuración F2 presente/ausente, estado/onboarding. Censar únicamente
   los conteos y las identidades necesarios: managed binding, 33/1 change
   bindings históricos, presupuestos, reservaciones, jobs/candidates,
   auth/audit. No copiar valores sensibles a PR/logs.
3. Verificar **por separado** cada managed root, marker de propiedad, origin,
   rama HEAD, diffs dirty (sin divulgación de secretos), OpenSpec/config,
   skills/workflows nativos, contexto realmente aprobado e identidad GitHub.
   Nunca cruzar la identidad/autenticación de `mini-me` y el fixture.
4. Clasificar con evidencia los bloqueos concretos de configuración:
   `tickets` y `git_pr` por proyecto; cuatro perfiles explícitos con
   modelos/esfuerzos/workflows/skills observados; capacidad, permisos, 
   contexto autorizado y presupuesto. Sin suposiciones ni defaults
   improvisados; no utilizar el status legacy como autorización.
5. Reproducir en PostgreSQL **desechable** la cadena exacta desde el
   estado operativo observado, con copia representativa/restaurable;
   confirmar que ambas filas, bindings, historial, perfiles/documentos
   existentes, auth, presupuesto, evidencia de candidatos y relaciones
   sobreviven `upgrade/downgrade/restore`. Comprobar que no aparece
   proyecto duplicado, no se fuerza ZIP ni PR Greenfield históricos, no se
   marca un BROWNFIELD nuevo `PREPARED`.
6. Si faltan decisiones reales del operador (p. ej. selección de roles o
   credenciales), reportar el dato preciso. **No** ejecutar en producción
   migración, backup/escrituras ni cambiar readiness sin autorización de
   rollout separada. 7.1b permanece sin completar hasta obtener la prueba
   de continuidad y elegibilidad requerida para F3/F5/F6.

### B. Gate E2E sin modelos: 4.4 / 8.4

1. Releer checkpoint completo de `f2-e2e-gacela-20261023e`,
   evidencia del intento anterior, identidad managed repository, hash ZIP,
   Git worktrees, ramas locales/remotas y PR. Comprobar si existe un
   candidato retenido y si puede repararse **sin nueva inferencia**.
   Si no existe, registrar evidencia de pérdida de candidato y detener
   cualquier replay implícito.
2. Confirmar GitHub App grants reales (`contents/write`,
   `pull_requests/write`, `issues/write` donde aplique) **en el
   repositorio desechable exacto**. Revisar la capacidad del agente,
   identidad OAuth, selección de modelo y presupuesto explícito antes
   de dispatch. No ejecutar probes que consuman cuota si el preflight
   read-only/estático basta.
3. Revalidar en runtime aislado el conjunto de archivos **realmente
   instalado** por OpenSpec (incluido `.agents/skills/.openspec-target`),
   el catálogo/documentos/índice y el scope guard; hacer primero el mismo
   recorrido con agente simulado y Git/GitHub adapters controlados.
   Confirmar que la validación no rechaza artefactos oficiales y que
   un candidato real post-inferencia se preserva si falla un gate posterior.
4. Registrar claramente el costo/tope, el perfil exacto, el conteo máximo
   de invocaciones y la autorización concreta aplicable al nuevo
   Greenfield. No reutilizar un permiso anterior consumido ni canjear
   la concesión incremental. Si falta autorización inequívoca, detenerse
   con motivo concreto; no invocar Codex/AGY/OpenRouter.
5. Tras autorización y gates, permitir **una única** invocación Greenfield
   real y publicar el primer PR en el repositorio **desechable**.
   Registrar base/head SHA, modelo, tiempo, usage/costo observado,
   ZIP hashes, scope/índice/archivos y PR. Detenerse en HUMAN REQUIRED
   para revisión y merge humano; no simular autorización.
6. Solo tras observar el **merge real exacto** y el estado `PREPARED`,
   procesar el ZIP incremental con autorización independiente,
   misma estructura estándar, otro branch/PR; conservar `main`
   anterior hasta merge humano del segundo PR. Ante efectos ambiguos,
   conservar evidencia y no repetir llamadas pagadas.

### C. Cierre de aceptación: 8.5

- Reconciliar uno a uno Issue #170, tareas, specs y evidencia vinculada
  (PostgreSQL histórico, live GitHub App grant, Greenfield e incremental
  reales, merges humanos y costos), con faltantes explícitos.
- Pruebas focalizadas + full suite, Ruff, strict OpenSpec y diff check
  sobre el candidato **final**. Censar rutas/archivos ajenos, secretos,
  migraciones y código muerto sin tocar historia aplicada.
- Mantener PR #178 Draft y tareas 4.4, 7.1b, 8.4, 8.5 desmarcadas
  hasta completar **sus pruebas específicas**. No scheduler, no F3,
  no despliegue ni merge de PR #178. Sync/archive solo después de
  aceptación y merge humano correspondiente.

## Resultado de cada gate

Un único reporte conciso en español: `PASS/BLOCKED`, evidencia mínima
vinculable, SHA/identidades, uso monetario **si hubo invocación**,
próximo actor y la **única** condición real faltante. No gastar una
nueva invocación para explorar un fallo determinista o acceso insuficiente.
