# MM-R05 — quota-safe-execution-and-recovery

**Estado:** PLANNED; **Dependencias:** MM-R03 + MM-R04; preflight básico exigido desde MM-R01; **Entrega:** Progreso real sin perder cuota ni work; **no autoriza** activar scheduler/consumir cuotas sin aprobación; merge humano obligatorio.

## Business intent y antes/después
**Antes:** El servidor presenta waits de autenticación/cuota y reconciliación fallida en N01; las ventanas de uso pueden estar obsoletas y no hay garantía de anticipación de agotamiento.

**Después del despliegue:** Al alcanzar un límite real o acercarse a una etapa demasiado costosa, mini me espera sin gastar inferencia, conserva Run/Job/WT y reanuda solo cuando un proveedor autorizado demuestre capacidad.

## Specs mínimas que el agente debe elaborar durante `propose`
Cada Sxx se convierte en requisitos SHALL/SHALL NOT con al menos un escenario observable y un caso de rechazo/recovery. Se pueden agrupar specs relacionadas siempre que permanezca trazabilidad Sxx→test→evidencia; no basta con copiar esta lista a tasks. Source of truth: `docs/CHANGE_DELIVERY_CONTRACT.md` y docs canónicos.

### R05-S01 — Señales de capacidad
SHALL leer señales reales por proveedor cuando existan (usage, rate-limit/reset, auth); registrar timestamp/origen/confianza y nunca convertir un estado stale a AVAILABLE por default.

### R05-S02 — Presupuesto por etapa
SHALL estimar costo/capacidad del próximo segmento y tiempo máximo usando historial cuando haya datos; reservar margen conservador para completar checkpoint, sin afirmar conocimiento exacto de cuota no publicada.

### R05-S03 — Admission gate
SHALL limitar nuevas admisiones a las que puedan iniciar seguro y detener despachos cuando credenciales, permisos, presupuesto o capacidad insuficientes; mantener elegibilidad del resto de proyectos.

### R05-S04 — Continuidad de sesión
SHALL preservar working set, SHA, branch, contexto OpenSpec, logs/attempts, provider role, checkpoints y lease; al reanudar reutilizar same Run/Job/WT cuando es válido, jamás duplicar external actions a ciegas.

### R05-S05 — Retry taxonomy
SHALL diferenciar QUOTA, AUTH_REQUIRED, TRANSIENT, TOOL_MISSING, STALLED, WORKSPACE_CORRUPT y HUMAN_DECISION; sin ping-pong ni retry en bucle por tasa/credenciales. Reintentos requieren nuevo evento o condición observada.

### R05-S06 — Preemptivo y honesto
SHALL fraccionar trabajo en etapas OpenSpec terminables y verificar checkpoint entre etapas. Si el proveedor no revela quota restante, marcar UNKNOWN y gestionar riesgo, no prometer prevención absoluta.

### R05-S07 — N01 dura
SHALL reconciliar N01 con 4 attempts, worktree CREATED y modificaciones históricas; #152 se revisa y se integra solo tras E2E en Linux, sin producir nuevo Run.

### R05-S08 — Scheduler restart
SHALL permanecer disabled en prod hasta evidencia, autorización y capacidad comprobada; controlar DRAIN/WAIT sin usar fallback no aprobado.

## E2E obligatorios de etapa y de valor
Cada E0x debe describirse en OpenSpec como Given/When/Then con setup, salida y evidence path. Fake providers/mocks pueden servir a integration, **no** a la demostración de capacidad real. Además ejecutar regresión de R01–R04 y verificar en entorno desplegado.

### R05-E01 — Expira cuota auténtica
En entorno autorizado reproducir respuesta real o normalizada de un proveedor que agotó cupo en etapa acotada; no invocar nuevamente hasta reset confiable, conservar código y pasar a WAITING_CAPACITY.

### R05-E02 — Vuelve capacidad
Con señal real y cuenta habilitada, retomar *mismo* Run/Job y terminar etapa pendiente de OpenSpec sin volver a escribir lo ya hecho; comprobar attempts y recursos.

### R05-E03 — Reinicio en checkpoints
Matar proceso tras worktree/diff y tras side effect GitHub; reiniciar y corroborar no duplicidad y misma lineage.

### R05-E04 — Auth requerido
Forzar credenciales expiradas o invalidación auth: status AUTH_REQUIRED sin llamada premium adicional. Un operador confirma renovación, y una única continuación controlada produce evidencia.

### R05-E05 — Quota desconocida
Proveedor no expone remaining/reset: la UI informa UNKNOWN, no horario inventado; se permite solo etapa de presupuesto/ventana autorizados.

### R05-E06 — Double exhaustion
Ambos primarios agotados: no nueva admisión; fallback denegado = WAIT. Fallo de reviewer no promueve auto-review del ejecutor.

### R05-E07 — Postdeploy
Reinicio real del servicio QA y recuperación de un trabajo con checkpoint, evidenciando el mismo Job/PR tras restart, sin intervención ni costo no aprobado.

## Trabajo que debe quedar dentro del mismo Change
- Reutilizar provider_health_service, capacity_windows, budget, saga/recovery y scheduler, no introducir un second scheduler.
- Implementar policy gates con clocks persistidos y pruebas de stale/unknown por proveedor; conectar al stage OpenSpec runtime.
- Definir comprobación no destructiva N01 y plan de reconciliación post #152 compatible con seguridad y permisos Linux.

## No-goals y guardrails
NO continuar ejecutando alternativas bajo autorización implícita ni crear scheduler que se autoencienda con reboot. No inventar consumo predictivo cuando el proveedor no ofrece señal.

## Prueba de aceptación verificable
Registro de preflight y señales fuente, estados de espera/recuperación, same Run/Job/WT, traces auténticos del proveedor con secrets redactados, recurso remoto no duplicado, E2E de restart postdeploy.

## Migración, release y recuperación
Mantener scheduler inactive/disabled. Preferir escenarios inducidos reproducibles para error-handling sin consumir saldo y al menos un smoke live autorizado para ruta de recuperación. Respetar resets/cuotas. El `design.md` resolverá estrategia de migración/rollback cuando exista impacto de DB/Git/estado, y demostrará reconciliación tras failpoint. `DONE` exige TECHNICAL_PASS + E2E_PASS + DEPLOYED_VERIFIED y gates humanos/closure aplicables; antes de eso es `PLANNED`, `IN_PROGRESS` o `BLOCKED`, nunca entrega ficticia.

## Flujo permitido
Invocar el workflow agent-led `propose quota-safe-execution-and-recovery` en el agente disponible/instalado. Contrastar proposal/design/specs/tasks con esta ficha antes de `apply`. Cada modificación de alcance va por `update`. Verificar con `verify`, checks reales y guards; cierre `sync/archive` según contrato. **mini me coordina stages; la IA mediante OpenSpec escribe y verifica.**
