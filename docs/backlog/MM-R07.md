# MM-R07 — operational-control-and-human-attention

**Estado:** PLANNED; **Dependencias:** MM-R03–R06; **Entrega:** Operador entiende, atiende y recupera sin DB; **no autoriza** activar scheduler/consumir cuotas sin aprobación; merge humano obligatorio.

## Business intent y antes/después
**Antes:** Existen UI/PWA/TUI y 5 Issues N01–N05, pero el usuario no puede ver con confianza qué ejecuta el sistema y por qué no continúa.

**Después del despliegue:** En móvil se ve estado/atención; en tablet se opera; en desktop se gestiona control center, con exactamente la misma fuente durable de estado y acciones de recuperación seguras.

## Specs mínimas que el agente debe elaborar durante `propose`
Cada Sxx se convierte en requisitos SHALL/SHALL NOT con al menos un escenario observable y un caso de rechazo/recovery. Se pueden agrupar specs relacionadas siempre que permanezca trazabilidad Sxx→test→evidencia; no basta con copiar esta lista a tasks. Source of truth: `docs/CHANGE_DELIVERY_CONTRACT.md` y docs canónicos.

### R07-S01 — Causas reales
SHALL exponer motivos normalizados desde evidencia del Run/Job/Issue: PROVIDER_CAPACITY, AUTH_REQUIRED, HUMAN_DECISION, DEPENDENCY, READINESS, TECHNICAL_FAILURE, UNKNOWN; prohibido adivinar.

### R07-S02 — Atención humana
SHALL renderizar pregunta/decisión genuina con actor, opciones/impacto, permisos y respuesta durable; controles para auth/budget/continue diferenciados de preguntas de producto.

### R07-S03 — Controles seguros
SHALL usar ControlPlaneService con optimistic concurrency, idempotency keys y audit trail; acciones no saltan gates, ni redefinen manualmente estados de BD.

### R07-S04 — Tres entornos
Mobile: qué hace, qué hizo, qué viene y si requiere atención. Tablet: master/detail con operación real. Desktop: control center denso, paneles resizables/persistidos, modales/drawers y jerarquía clara.

### R07-S05 — Plan y dependencias
SHALL mostrar orden de admisión estimado, incertidumbre de cuota, grafo de dependencias, prioridades y razones de bloqueo alineadas al mismo cálculo scheduler, sin promesa inventada.

### R07-S06 — Read models
SHALL evitar que TUI/PWA consulten PostgreSQL directamente o dupliquen lógica; APIs deben representar exactamente estados y autorizaciones.

### R07-S07 — N01–N05
SHALL reconciliar Issues #133/#138 N01 y mapear #134–#137 a escenarios sin dos pipelines paralelos; preservar historian.

## E2E obligatorios de etapa y de valor
Cada E0x debe describirse en OpenSpec como Given/When/Then con setup, salida y evidence path. Fake providers/mocks pueden servir a integration, **no** a la demostración de capacidad real. Además ejecutar regresión de R01–R06 y verificar en entorno desplegado.

### R07-E01 — N01 auténtico
Inspeccionar el bloqueo real del N01 en servidor (sin continuar al agente) y ver en PWA/TUI la clasificación fiel de auth/quota, intento y decisión disponible.

### R07-E02 — Respuesta de humano
Producir NEEDS_HUMAN legítimo en QA, responder desde UI y observar misma Run/Job continuar sin acciones repetidas ni privilegios elevados.

### R07-E03 — Capacidad versus humano
Provocar WAITING_CAPACITY y mostrarlo como espera, nunca pregunta humana, con reset UNKNOWN si no hay señal.

### R07-E04 — Dos operadores simultáneos
Enviar dos acciones con versión anterior: una gana, la otra conflicto entendible; no dos external calls.

### R07-E05 — Browser real
Comprobar estado, atención, navegación, modales, foco, tamaño y permisos en Chrome desktop/tablet/mobile con capturas y escenarios de validación humana.

### R07-E06 — Postdeploy remoto
Desde la URL pública autenticada ver estado actualizado del Run real, bloquear acceso no autorizado y resolver una acción QA permitida sin SSH ni DB.

## Trabajo que debe quedar dentro del mismo Change
- Consolidar lectura operativa de API/TUI/PWA, reutilizar tarjetas y flows útiles N01–N05 en vez de cinco mini-implementaciones.
- Unificar el cálculo plan scheduler, dependencia y opciones autorizadas; trazar controles hasta mutaciones durables.
- Diseñar pruebas E2E de browser y API, verificación de screens con usuario en escenarios donde su juicio es requisito.

## No-goals y guardrails
NO dashboard de vanity metrics, rediseño total PWA, cosmética no vinculada a fallas reproducibles, ni modificación ad hoc de scheduler por conveniencia UI.

## Prueba de aceptación verificable
Sesión Chrome con estados reales, correlación API/DB, respuesta durable con actor/timestamp, E2E concurrentes, visuales desktop/tablet/mobile y validación de destino público.

## Migración, release y recuperación
Feature flag por vista o route; no romper logins OAuth existente. Verificar protección de endpoints y session expirations tras despliegue. El `design.md` resolverá estrategia de migración/rollback cuando exista impacto de DB/Git/estado, y demostrará reconciliación tras failpoint. `DONE` exige TECHNICAL_PASS + E2E_PASS + DEPLOYED_VERIFIED y gates humanos/closure aplicables; antes de eso es `PLANNED`, `IN_PROGRESS` o `BLOCKED`, nunca entrega ficticia.

## Flujo permitido
Invocar el workflow agent-led `propose operational-control-and-human-attention` en el agente disponible/instalado. Contrastar proposal/design/specs/tasks con esta ficha antes de `apply`. Cada modificación de alcance va por `update`. Verificar con `verify`, checks reales y guards; cierre `sync/archive` según contrato. **mini me coordina stages; la IA mediante OpenSpec escribe y verifica.**
