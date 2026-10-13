# Disciplina de ingeniería obligatoria — mini me

## 1. Origen, autoridad y propósito

**Esta disciplina se deriva de las reglas fundacionales de AgentFlow/mini me y del estado canónico vigente; no es una nueva vía de programación al margen de OpenSpec.** Las reglas originales especificaban que:
- Un Change entrega **valor real, independientemente verificable**, y puede comprender múltiples specs/capacidades.
- OpenSpec contiene contratos de comportamiento; `design.md` gobierna decisiones arquitectónicas; `tasks.md` ordena la implementación.
- Solo se implementa el Change activo, sin adoptar trabajo posterior oportunistamente.
- El daemon/core coordina; las UIs consumen API; Git y estado operacional mantienen autoridades separadas.
- Los agentes permanecen en el workspace autorizado, preservan código no relacionado y detienen ambigüedades que cambian comportamiento.
- Cada tarea completada requiere evidencia; checks, revisión independiente de corrección/regresiones/seguridad/**mantenibilidad**, resiliencia y observabilidad son requisitos.
- La autoridad de merge, secretos y gasto extraordinario sigue en manos del operador.
- UX no es opcional: cuando el cambio toca experiencia de operador, esta debe ser utilizable, observable y verificable.

**Desarrollos posteriores concretan** esas reglas mediante PostgreSQL/Alembic, GitHub App, claims, fencing, idempotencia, validación post-despliegue, guardrails E2E y uso de workflows OpenSpec nativos. La eliminación de código reemplazado y el inventario de acoplamientos se agregan expresamente como **controles correctivos de esta revisión**, sin afirmar que figuraban literalmente en el documento del primer día.

Léase con `BUSINESS_INTENT.md`, `CANONICAL_DECISIONS.md`, `ARCHITECTURE.md`, `AGENT_CONTRACTS.md`, `DOR_DOD.md`, `CHANGE_DELIVERY_CONTRACT.md` y el único Change OpenSpec autorizado. Una regla contradictoria no se ignora ni se resuelve con creatividad del agente: **BLOCKED → `update` de OpenSpec + decisión humana material**.

## 2. Disciplina de diseño ANTES de `apply` (Engineering G1)

Para cualquier Change y para **cada spec** que lo integra:
1. **Trazabilidad:** business intent → resultado observable → requisito SHALL/SHALL NOT → escenario → test E2E → evidencia del destino. Definir condiciones negativas, fallos, límites y regresiones.
2. **Censo de código y capacidades:** buscar los componentes existentes, consumidores, writers/side effects, hooks, skills, commands, guards, harnesses, scripts, documentación, suites y rutas de despliegue que participan en el comportamiento. Registrar exactamente lo que se reutiliza, modifica, sustituye o elimina. **No asumir que un módulo es código muerto por su nombre.**
3. **Diseño mínimo coherente:** evaluar alternativas, justificar elegir servicios/proveedores existentes antes de crear nuevos. Principios de diseño: separación de responsabilidades, cohesión, acoplamiento controlado, interfaces explícitas, bajo duplicado, simplicidad apropiada; sin frameworks genéricos especulativos ni abstracciones que no justifican valor.
4. **Fronteras e invariantes:** responsabilidades separadas mini me/agents/OpenSpec/Git/GitHub/PostgreSQL; identidad verificada repo/worktree; autenticación y autorización; idempotencia, concurrencia, claims/fencing, estado durable y side effects UNKNOWN, cuidado con rollback y migraciones.
5. **Contrato del agente:** nombrar la skill/command real instalada, los hooks/guards permitidos, su orden y su evidencia de invocación; no reemplazar con prompt libre. El agente produce el software y las specs mediante OpenSpec.
6. **Diseño de pruebas, no lista de aspiraciones:** fixtures, datos, endpoints, límites de cuota, secuencia, esperados, verificación negativa y rollback para E2E de cada etapa, Change y comportamiento ya desplegado.
7. **Impacto de retirada:** preparar **Removal Ledger** antes de comenzar `apply`, incluso si el valor del Change es funcional y no una migración. Marcar `NONE` con evidencia si realmente no se reemplaza nada.

`proposal` y `design` no pasan si están incompletos estos puntos; un check superficial de existencia de archivos no es suficiente.

## 3. Calidad de implementación DENTRO de `apply` (Engineering G3)

- Escribir exclusivamente dentro del Change/worktree/autorización; el agente no convierte deuda no relacionada en cambios oportunistas.
- Preservar contratos públicos que sigan usados. Si una API/schema/CLI/config necesita cambiar, incluir sus consumidores, versión, política de compatibilidad y migración; no introducir cambios incompatibles silenciosos.
- Priorizar decisiones simples, código legible y mantenible, responsabilidades acotadas, reducción de duplicación y reutilización de herramientas oficiales. Los contratos existentes determinan estilo/lint/formato/tipado; nuevos estándares se declaran en `design`, nunca se inventan al ejecutar.
- Pruebas de fallos, seguridad, idempotencia, concurrencia, permisos y capacidad deben acompañar la implementación. Mocks son útiles para pruebas unitarias/contrato, pero no acreditan el E2E de proveedor, GitHub, OpenSpec o despliegue.
- No fingir resultados, escribir datos de producción para pasar tests, degradar una aserción, marcar tareas completas sin evidencia, ni usar excepciones silenciosas.
- Integración continua: tests, lint, formato, tipado estático cuando aplique y análisis de seguridad/dependencias configurados por el proyecto; verificar incompatibilidades reales y fallo de migración con datos representativos.
- La mejora debe ser operable y observable en web/tablet/móvil cuando afecte a UI: jerarquía, usabilidad, acciones autorizadas, densidad apropiada, feedback, accesibilidad y comprobación en navegador real.
- Cambios de specs se hacen vía workflow OpenSpec `update`, con revalidación de la matriz de trazabilidad.

## 4. Desmonte obligatorio de código obsoleto (Engineering G4-R: Removal Gate)

**Regla:** Todo Change que sustituya un comportamiento debe retirar en el **mismo Change**, antes del merge y cierre, su ruta vieja **cuando la nueva ruta haya superado paridad y E2E**. Nunca dejar el sistema ejecutando dos fuentes de verdad por defecto ni aplazar el desmonte sin un plan explícito autorizado.

**Removal Ledger**, exigido por cada Change:
| Campo | Qué registrar |
|---|---|
| Replaced behavior | Qué comportamiento ha quedado cubierto por el nuevo workflow/harness |
| Old entrypoints/writers | Archivos, símbolos, CLI, rutas HTTP, jobs, dispatches y escrituras antiguas |
| Reachability/consumers | Búsqueda de imports, referencias, dependency injection, llamadas dinámicas, configuración, scripts, tests y despliegues |
| Migration / historical owners | Datos, migraciones Alembic, OpenSpec archivados, Run/Job/attempts, métricas y enlaces durables que **NO** se deben borrar |
| New authority | Nuevo componente/workflow OpenSpec, provider/skill/hook real, su validación E2E y SHA de paridad |
| Actions | REMOVE / MIGRATE / RETAIN-WITH-REASON por elemento |
| Evidence | Grep/referencia estática, tests red/green, invocación E2E, SHA/diff, rollout/rollback |
| Final state | No callers huérfanos, no rutas duplicadas activas, no fallback silencioso, no tests simulados haciéndose pasar por E2E |

**Secuencia innegociable:**
1. Inventariar con herramientas estáticas y flujos dinámicos el uso real; incluir rutas por plugins/reflection que un simple grep no vea. No catalogar como muerto algo usado por recovery o datos históricos.
2. Probar la alternativa nueva con E2E real y checks, con preservación de histórico/candidate.
3. Migrar todos los **consumidores**, invocaciones de UI/CLI/API, jobs, configuración, permisos, guards/hooks/skills, documentación de operador, scripts y escenarios de prueba que apunten a la ruta vieja.
4. Eliminar implementación anterior, flags transitorios, código de compatibilidad sin consumidores, adaptadores, tests exclusivos de comportamiento retirado, dependencias/imports huérfanos y documentación contradictoria **que sea seguro retirar**. Sustituir tests valiosos por tests del nuevo contrato, no borrar protección de regresión.
5. Repetir tests unit/integration, E2E de etapa, E2E de valor y regresión **después** de eliminar código, no aceptar las pruebas tomadas con ambos caminos presentes.
6. Verificar en el entorno desplegado que solo la ruta vigente es alcanzable; no dejar feature flag que vuelva al emulador; registrar evidencia de no referencias, no writers duplicados, diff y rollback.
7. Si la eliminación inmediata amenaza seguridad, histórico, datos o disponibilidad, **NO** borrarla a ciegas: marcar `RETAIN-WITH-REASON`, explicar el bloqueante, límite temporal y el Change específico que completa retiro; exigir **autorización humana explícita** para excepción. El Change no se presenta como “desmonte completo” ni `DONE` si quedaron rutas obsoletas activas.

**NO eliminar:** specs OpenSpec históricos ni archivos archivados por mero refactor, migraciones ya aplicadas, audit trails, Run/Job/attempts/evidencias, compatibilidad que todavía tenga consumidores legítimos o worktrees ajenos/dirty. Los archivos históricos pueden conservarse como archivos de archivo, etiquetados como no ejecutables, sin alterar su verdad.

**No crear un Change genérico de limpieza global**: cada reemplazo se retira en el Change que entrega su sustitución. Solo hacer un Change de retiro por separado si hay justificación contractual y una dependencia demostrada que hace inseguro el retiro simultáneo.

## 5. Revisión y validación ANTES del PR (Engineering G4/G5)

El revisor independiente no solo revisa si los tests pasan: compara `BUSINESS_INTENT`, las specs y criterios del Change, el diseño aprobado y el código/diff final **después del desmonte**.

Bloquear si:
- Hay funciones/servicios sin consumidores justificados, rutas duplicadas, código temporal de producción sin plan, flags muertos, imports/configuración obsoletos, o el Remove Ledger carece de evidencia.
- El implementador hizo arquitectura nueva fuera de las specs, violó separación de capas, expuso secretos o permisos, reimplementó capacidades oficiales, eliminó guards, omitió migración, dejó API incompatibles o introdujo regressiones.
- Tests no comprueban casos adversos/E2E reales, evidencias no coinciden con candidate SHA, hay skips ocultos o pruebas condicionadas a plataforma incorrecta.
- El revisor no es independiente, falla la validación estática requerida, no hay E2E post-retiro o postdeploy, o no existe un rollback viable.

Un hallazgo se resuelve mediante `update/apply/verify` según workflow; no con prompts improvisados ni revisión cosmética. Admitir explícitamente incertidumbre donde una regla no pueda comprobarse automáticamente; no afirmar que un hook infalible detecta todo drift.

## 6. Resultado de cada entrega y control posterior

**PASS técnico** = funciones/tests/checks; **PASS integración** = colaboración/resiliencia; **E2E_PASS** = agente y workflows reales + Git/PR/side effects; **DEPLOYED_VERIFIED** = valor usable en destino y regresiones verificadas **después del Removal Gate**.

El DoD exige matriz requisito→escenario→test→evidencia + ledger de retiro `NONE` justificado o cada acción finalizada + revisión independiente + seguridad/observabilidad + UX aplicable + despliegue funcional + cierre/human gates. Si falta cualquiera: `BLOCKED`, no un “PASS parcial” reconvertido en `DONE`.

**Atribución y trazabilidad:** el reporte de release enlaza Issue, OpenSpec change, candidate SHA, agent workflow/skill/harness/guard, suite, E2E, PR, diff de retiro, deployment digest, resultado postdeploy, métricas de costo y autorización humana. El servidor debe poder reanudar/explicar el trabajo sin que una conversación de ChatGPT actúe como autoridad.

## 7. Aplicación por etapas

- **MM-R01:** reemplaza prompts de implementación ad hoc por invocación agent-side OpenSpec; retirar rutas de ejecución imitadas solo cuando paridad E2E esté probada.
- **MM-R02:** retirar el writer determinístico de proposals/design/specs/tasks, las llamadas desde Intake y sus fixtures desactualizadas.
- **MM-R03:** consolidar orquestación/admisión y prompts de handoff antiguos, dejando una ruta efectiva por stage.
- **MM-R04:** retirar los mergers/archivers semánticos Python tras native sync/archive E2E; preservar reconciliación GitHub/DB/externa y seguridad.
- **MM-R05:** retirar políticas, adaptadores y probes de cuota obsoletos únicamente si hay prueba de reemplazo funcional.
- **MM-R06:** retirar registries/harness/skills duplicados y dependencias redundantes después de demostrar uso real del catálogo vigente.
- **MM-R07:** retirar proyecciones de estado, acciones y UI duplicadas sin perder autorizaciones/historia.
- **MM-R08:** eliminar supuestos `mini-me`-only en rutas generales tras 2-repo E2E.
- **MM-R09:** retirar ejemplos/stubs/descriptores de capacidades reemplazadas tras pruebas de consumo y rollback.
- **MM-R10:** retirar la coordinación manual residual que ya no tiene consumidores, pero conservar gates humanos obligatorios.

**La eliminación real se realiza por los agentes mediante el `apply` OpenSpec del Change; este archivo es contrato, no instrucciones para borrar código ahora.**
