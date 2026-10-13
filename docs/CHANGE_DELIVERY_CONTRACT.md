# Contrato de entrega vertical, OpenSpec y E2E — mini me

## 1. Jerarquía de autoridad y función de cada sistema

- **Human owner:** decide ambigüedades materiales, presupuestos extraordinarios, secretos, políticas, validación visual cuando corresponde, merge y rollback.
- **GitHub:** cartera, Issue, PR, aprobaciones; los campos del Project no autorizan selección de repositorio.
- **OpenSpec:** intención de cambio, `proposal`, `design`, `specs`, `tasks` y workflows cognitivos `propose/update/continue/apply/verify/sync/archive`, según perfil instalado.
- **Codex / Antigravity:** usan OpenSpec y capacidades del repo para razonar, escribir artefactos/código, corregir, verificar y revisar. Roles por **etapa y candidato**, no por modelo perpetuo.
- **mini me:** identifica proyecto y autoridad, asigna stage/ejecutor/reviewer, selecciona capacidades, prepara sandbox/worktree, controla tiempo/cuota, dispara el workflow del agente, observa evidencia, persiste intentos y avanza gates, entrega GitHub/PR y acciones determinísticas seguras.
- **PostgreSQL:** estado/eventos/intentos/locks/cuota/evidencia durable; jamás autoridad de especificación.
- **Git:** modificaciones, worktrees, candidatos/SHAs, historia/entrega.
- **DeepSeek/OpenRouter:** alternativas solo cuando ambos primarios no puedan cubrir una etapa, tras autorización explícita con presupuesto y compatibilidad real de herramientas; no imponer auditoría DeepSeek rutinaria. DeepSeek API **no equivale** por sí misma a ejecutor coding-tool con invocación de skills.
- **Qwen local:** diagnóstico/ayuda acotados y no autoritativos; no reemplaza agente SDD ni review de calidad.

**Guard invariable:** mini me NO construye `proposal.md`, `design.md`, `tasks.md`, `specs/*.md` ni código como sustituto del workflow del agente. Puede crear scaffolding o verificar/registrar artefactos sin decidir su contenido. No debe reimplementar `sync`/`archive` semánticos. Solo se autoriza excepción de bootstrap/migración explícitamente aprobada en OpenSpec, documentada y reversible; sin desviaciones implícitas.

## 2. Unidad indivisible de entrega

Cada Change debe contener las specs necesarias para ofrecer **una capacidad utilizable al desplegarse** (backend, DB, UI, proveedor, seguridad, Git, telemetría, tests E2E), no una sola spec ni un subsistema sin producto. Puede ser un Change con muchas specs. Cada ficha MM-Rxx declara el valor y la matriz de specs mínimas; el agente puede añadir specs indispensables en `propose` documentando por qué son necesarias, sin ampliar el resultado ni improvisar arquitectura.

**Contrato de un Change al proponer (gate previo a apply):**
1. `proposal.md`: problema, actor, antes/después, resultado observable, métrica, dependencias, alcance/no-goals y plan de adopción.
2. `design.md`: call graph real, límites mini me/agent/OpenSpec, componentes existentes reutilizados o reemplazados, seguridad, identidad repo/worktree, presupuesto/abort/resume, rollback/despliegue, migraciones compatibles y plan de pruebas.
3. `specs/<capability>/spec.md`: SHALL/SHALL NOT y escenarios Given/When/Then para éxito, rechazos, idempotencia, fallos, reinicios, multi-repo y UX cuando apliquen.
4. `tasks.md`: implementación + unit/integration + E2E de etapas + E2E de valor + E2E postdeploy + revalidación/regresión + evidencia + clausura. Cada tarea con evidencia verificable, sin checkboxes decorativos.
5. Matriz trazable `business intent → capability/spec → scenario → test → evidencia → entregable`. Cambios de spec revalidan esta matriz.
6. Regla **anti-drift**: revisión de contradicción con `BUSINESS_INTENT`, `PRODUCT`, `CANONICAL_DECISIONS`, contrato presente y specs activas. Anomalía material = BLOCKED hasta reconciliación formal del Change; ningún auditor reemplaza esta comprobación determinística.
7. Revisión de OpenSpec/agent capabilities instaladas, su versión y compatibilidad; decidir explícitamente reuse o deprecación, con prueba de las invocaciones reales por proveedor. No inventar binarios `opsx`.

## 3. Pruebas obligatorias: sin falso E2E

- **Unit:** funciones/reglas; soporte pero nunca aceptación.
- **Integration:** adaptadores reales/DB/Git/scheduler bajo fronteras relevantes; mocks solo para prueba de contrato acotada.
- **E2E por etapa:** entrada/ejecutor/workflow/salida/evidencia real de cada transición que introduce el Change.
- **E2E completo de valor:** API/UI/GitHub real en entorno aislado representativo con **agente real cuando la capacidad reclamada usa agentes**, OpenSpec real, Git real, estados reales y evidencias asociadas al run.
- **E2E posterior al despliegue:** aplicación accesible por ruta real; verificar resultado, no solo health `200`. Para UI, navegador real con desktop/tablet/mobile según vista y escenario humano registrado.
- **Regresión E2E:** repertorio de capacidades verticales previamente aceptadas, priorizadas por criticidad. No usar una prueba simulada para afirmar que un agente completó `apply`.
- **Adversarial:** al menos los fallos relevantes del Change: cuota/auth/timeouts, crash/restart, side effect desconocido, conflict de Git, permisos, drift, duplicidad, independencia reviewer, costo no autorizado, fallo rollback, según riesgo.
- Un E2E con inferencia tiene preflight y presupuesto autorizados, límite de duración/intent-os, fixtures pequeños y checkpoint. Se **reutiliza evidencia aún válida** por SHA/config/provider y no se vuelve a llamar agentes innecesariamente para comprobar lo determinístico.
- No es admisible llamar “E2E” a `fake_runner`, stubs de GH, asserts de mocks, navegación sin acciones reales o sólo `pytest 100%`. Cuando una prueba real no se pudo ejecutar: **NOT VERIFIED / BLOCKED**, jamás PASS.

## 4. Gates innegociables

| Gate | Requisito | Falla esperada |
|---|---|---|
| G0 — Intake | Dueño/intent, repo/Issue binding, Scope/no-goals, permiso | no admission |
| G1 — Propose | Artefactos agent-led coherentes, specs de valor, DoR/anti-drift | no apply |
| G2 — Preflight | Git/WT seguros, herramientas/skills instalados, cuenta/auth, capacidad/budget, restore path | no inference |
| G3 — Apply | Workflow real de agente, source diff dentro de scope, lineage de attempts | preserve and wait |
| G4 — Verify/review | Checks, workflow verify y revisión por identidad independiente; riesgos resueltos | no PR-ready |
| G5 — PR/human | Candidate SHA, escenarios E2E ejecutados, human merge authority | no merge |
| G6 — Closure | Merge observado, specs nativas sincronizadas/archivadas, despliegue y E2E productivo | no DONE |

**No permitidos:** saltar gates por `override` implícito; auto-merge; llamar DeepSeek/OR sin autorización; reintentar un side effect incierto sin observar; destruir N01/candidato/worktree para que las pruebas pasen; llamar “entregado” a un documento o suite técnica.

## 5. Seguridad, cuotas, recuperación y despliegue

- Scope de lectura/escritura estrictamente dentro de repo gestionado y workspace asignado. Validación contra git remote/base SHA, symlinks/path escapes y comandos destructivos.
- Preflight de tools/harness/skills y auth sin consumir inferencia; si cuota exacta desconocida, no inventar porcentaje o reset, reservar paso limitado y checkpoint seguro. No afirmar protección predictiva que el proveedor no permite.
- Claims, fencing, idempotencia y fases de side effect perduran. Una acción UNKNOWN exige observación autoritativa antes de repetir. Resume en el mismo Run/Job/worktree cuando contratos permiten; no crear un duplicado silencioso.
- Si no hay capacidad autorizada, `WAITING_CAPACITY`, no error humano; si falta decisión legítima, `NEEDS_HUMAN` con motivo/impacto y opción segura.
- El despliegue separa migraciones expand/contract, snapshot/backup necesarios, smoke, rollback y verificación de seguridad. Nunca poner scheduler productivo RUN antes de probar capacidad/convergencia y recibir autorización.
- Clasificación P0/P1 ante falla de seguridad/corrupción/no merge authority, P2 para blocking delivery, P3 cosmetic. No nuevas “microcorrecciones” sin trazabilidad a un Change vertical.

## 6. Evidencias auditables mínimas

Cada E2E: `change_slug`, `scenario_id`, run/job/attempt, fecha, repo_id/remote, base/head SHA, OpenSpec CLI versión/perfil/workflow, proveedor/modelo y rol, herramienta/skill/hook invocado, comandos/checks y exit, artefactos observados, diff, revisión independiente, PR y merge si aplica, destino de despliegue/image digest, prueba de comportamiento en producción, diagnóstico de bloqueos y costos autorizados. Evidencia sensible redactada.

El reporte de entrega tiene tres resultados **diferentes**: `TECHNICAL_PASS` (unit/integration), `E2E_PASS` (capacidad realmente ejercitada), `DEPLOYED_VERIFIED` (valor observado en el destino). Para Change completo, `DONE` exige el tercero y cierre/human gates aplicables. Si un proveedor falta, admitir `WAITING_CAPACITY` con trazabilidad; no declarar éxito.

## 7. Ejecución disciplinada del roadmap

- Un Change **activo** a la vez por defecto. Escribir estos documentos NO crea 10 cambios activos.
- Convertir ficha a OpenSpec mediante `propose` del agente, no mediante plantillas de Python de mini me.
- `update` ante cambio de interpretación; `apply` por implementador; `verify` por agente y guard de evidencia; `sync/archive` en cierre autorizado. `continue` donde la instalación lo tenga disponible.
- Forma de invocación según herramienta: Codex suele usar `$openspec-propose`; otras integraciones usan `/opsx-propose` o `/opsx:propose`. Es **un workflow dentro del agente**, no un subcomando de shell. La configuración instalada manda.
- No empezar el siguiente Change mientras el anterior tenga defectos que impidan su valor anunciado o su release E2E. Si el Change crea PR y espera merge humano, el gate humano es el resultado observable previsto hasta ese punto; no confundir con DONE del change tras merge/despliegue.
