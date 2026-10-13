# MM-R06 — project-aware-agent-capabilities

**Estado:** PLANNED; **Dependencias:** MM-R05 (elementos esenciales desde R01); **Entrega:** Agente correctamente equipado con capacidades del proyecto; **no autoriza** activar scheduler/consumir cuotas sin aprobación; merge humano obligatorio.

## Business intent y antes/después
**Antes:** Existen skills/commands de OpenSpec y guards en .agent/.agents, además de un PR #140 abierto con quality hooks, pero no está demostrado su uso selectivo y trazable en el run real.

**Después del despliegue:** Al comenzar cada etapa, mini me selecciona el contexto permitido y el agente real carga los skills/hooks/commands/harnesses adecuados; se observa que cambiaron efectivamente el resultado y bloquearon una violación.

## Specs mínimas que el agente debe elaborar durante `propose`
Cada Sxx se convierte en requisitos SHALL/SHALL NOT con al menos un escenario observable y un caso de rechazo/recovery. Se pueden agrupar specs relacionadas siempre que permanezca trazabilidad Sxx→test→evidencia; no basta con copiar esta lista a tasks. Source of truth: `docs/CHANGE_DELIVERY_CONTRACT.md` y docs canónicos.

### R06-S01 — Discovery de capacidades
SHALL inventariar skills, commands, workflows, hooks, guards y harnesses del repo + biblioteca permitida, versionados por hash/origen/permisos/tool/provider; respetar convenciones locales.

### R06-S02 — Selección por stage
SHALL mapear tipo de Change/stage/riesgo a capacidades compatibles instaladas; resoluciones auditables, no prompts mastodónticos, no ejecutar herramientas ausentes.

### R06-S03 — Orden y precedencia
SHALL anteponer guards de seguridad/arquitectura a extensiones de project; jamás permitir que un hook modifique permisos, budget o merge policy.

### R06-S04 — Contexto delimitado
SHALL entregar Business Intent, specs activas, contexto del Change, dependencias y archivos pertinentes con protección de secretos/tokens, sin recortar reglas esenciales.

### R06-S05 — Harness por agente
SHALL traducir abstracción común a la forma real del proveedor (Codex skill, Antigravity workflow, CLI y argumentos soportados) con prueba de loading efectivo; la presencia de archivo no equivale a ejecución.

### R06-S06 — Hooks en gates
SHALL comprobar PRE-PROPOSE/APPROVE, PRE-APPLY, POST-APPLY, VERIFY, ARCHIVE cuando corresponda; hooks pueden bloquear o señalar evidencia, no declarar un pass por si mismos.

### R06-S07 — Racionalizar PR #140
SHALL evaluar PR #140 por seguridad/scope/no false pass, reutilizar cambios compatibles o registrar rechazo; sin copiar framework alternativo paralelo.

### R06-S08 — Sin nueva biblioteca obligatoria
SHALL preservar capacidad fallback de componentes existentes y reusar primero skill OpenSpec oficial; ningún registro complejo previo a demostrar el run.

## E2E obligatorios de etapa y de valor
Cada E0x debe describirse en OpenSpec como Given/When/Then con setup, salida y evidence path. Fake providers/mocks pueden servir a integration, **no** a la demostración de capacidad real. Además ejecutar regresión de R01–R05 y verificar en entorno desplegado.

### R06-E01 — Selección y uso real
En dos repos fixture con AGENTS/skills distintos, el mismo tipo de Change selecciona el conjunto propio correcto, un agente ejecuta OpenSpec y trace prueba uso del skill/hook requerido.

### R06-E02 — Hook anti-drift
Inyectar instrucción que sustituya OpenSpec por Python generator; guard de pre-apply bloquea, reporta autoridad violada y no llama implementación.

### R06-E03 — Intento malicioso
Skill de proyecto solicita escritura fuera de workspace, filtración de secreto o auto-merge; policy harness impide efecto y mantiene estado.

### R06-E04 — Missing capability
Skill requerido no instalado o versión incompatible: BLOCKED con indicación precisa de remediación, sin silently downgrade a prompt genérico.

### R06-E05 — Outcome sustancial
Ejecutar change con capacidad seleccionada que produce prueba verificable (por ejemplo un hook detecta una inconsistencia y obliga `update`/reverify). Demostrar diferencia versus control.

### R06-E06 — Postdeploy
Ejecutar por la API productiva/QA los mecanismos de selección y comprobar en logs del host qué skill/hook se invocó por etapa; no solo registry en BD.

## Trabajo que debe quedar dentro del mismo Change
- Integrar catálogo mínimo y resolver existing .agent/.agents/OpenSpec config, no reescribir OpenSpec init.
- Introducir lineage de capability version/hash, policy check y evidencia de uso real por agente.
- Revisar #140 con matriz contra Change Delivery Contract y aceptar únicamente la porción que pase E2E.

## No-goals y guardrails
NO marketplace de skills, versiones comerciales, auto-creación de nuevos harnesses (R09), proveedores ficticios o modelos sin herramienta de escritura capaz.

## Prueba de aceptación verificable
Trace real + manifest capacidades por stage con hash, outputs de gates antes/después, diff generado con skill correcto, E2E de denial en 2 repos, UI/API de progreso sin secretos.

## Migración, release y recuperación
Activar catálogo mínimo en modo observación, luego fail-closed para capacidades obligatorias. Versionar cambios de hooks y probar rollback si bloquean legítimas ejecuciones. El `design.md` resolverá estrategia de migración/rollback cuando exista impacto de DB/Git/estado, y demostrará reconciliación tras failpoint. `DONE` exige TECHNICAL_PASS + E2E_PASS + DEPLOYED_VERIFIED y gates humanos/closure aplicables; antes de eso es `PLANNED`, `IN_PROGRESS` o `BLOCKED`, nunca entrega ficticia.

## Flujo permitido
Invocar el workflow agent-led `propose project-aware-agent-capabilities` en el agente disponible/instalado. Contrastar proposal/design/specs/tasks con esta ficha antes de `apply`. Cada modificación de alcance va por `update`. Verificar con `verify`, checks reales y guards; cierre `sync/archive` según contrato. **mini me coordina stages; la IA mediante OpenSpec escribe y verifica.**
