# MM-R09 — governed-agent-capability-evolution

**Estado:** PLANNED (no activo). **Dependencias:** MM-R06–MM-R08. **Capacidad entregada:** Creación gobernada de skills, hooks y harnesses reutilizables.

## Business intent: problema → resultado real
**Antes:** La biblioteca de capacidades existentes puede no satisfacer tareas futuras; crear scripts ad hoc rompe arquitectura y desvía a mini me de su papel de orquestador.

**Después de desplegar:** Si una ejecución descubre una capacidad faltante, se genera un Change OpenSpec para que agentes diseñen, implementen, prueben y publiquen ese skill/hook/command/guard/harness, con revisión independiente y reuso posterior.

## Requisitos por spec (se implementan en un Change OpenSpec multi-spec)
Los Sxx son mínimos normativos. En `propose`, el agente clasifica las specs por comportamiento/capacidad, formula SHALL/SHALL NOT y escenarios Given/When/Then, resuelve tradeoffs en design, y crea tasks ordenadas incluyendo pruebas reales. No iniciar `apply` sin trazar todos los requisitos contra evidencia final y revisar no-goals.

### R09-S01 — Gap demostrable
SHALL registrar por evidencia la capacidad faltante, su efecto en la tarea, catálogo existente inspeccionado, alternativas evaluadas y decisión de construir; no autogeneración por curiosidad.

### R09-S02 — OpenSpec de capacidad
SHALL abrir work item/Issue con proposal/specs/design/tasks de la capacidad por workflow agent-led `propose`, usando criterios de actor, seguridad y aceptación E2E.

### R09-S03 — Implementación por agente
SHALL asignar agente que codifica skill/hook/harness en repo autorizado, empaqueta versión + schema de entradas/salidas, requisitos y permisos; mini me no crea el código o prompt libre.

### R09-S04 — Aislamiento y privilegios
SHALL evaluar comandos, side effects, secretos, networking, rutas y hooks para evitar escalamiento. Un hook de proyecto no puede conceder permisos ni superar guards canónicos.

### R09-S05 — Verificación y revisión
SHALL ejecutar tests de contrato y E2E que prueben un consumo auténtico del artefacto nuevo por otro stage/agente; revisor independiente verifica estabilidad, fallback y efectos negativos.

### R09-S06 — Publicación versionada
SHALL conservar provenance, owner, checksum, compatibilidad provider/OpenSpec, ejemplos mínimos, políticas de rollout, rollback e invalidación de cachés/contextos.

### R09-S07 — Aprobaciones
SHALL exigir merge humano y aprobación extraordinaria para nuevas capacidades que escriben o ejecutan herramientas de alto privilegio; no auto-activar una extensión de seguridad sensible.

### R09-S08 — Reuso
SHALL demostrar en un cambio posterior que se selecciona la versión correcta y un update rompe compatibilidad de forma fail-closed, no silenciosa.

## Escenarios E2E de etapa, Change y destino
Cada E0x es contractual y debe tener setup, ejecución, verificaciones de side effects y evidencias durables. Test mock-only no satisface un escenario que atribuye una acción a un agente/servicio real; un E2E no corrido es `BLOCKED` o `NOT VERIFIED`.

### R09-E01 — De gap a PR
En una fixture que requiere skill ausente, registrar gap, crear OpenSpec por agente, implementar skill por otro stage de agente, review independiente y PR real sin escritura mini me.

### R09-E02 — Consumo real
Después del merge autorizado, correr un Change que usa efectivamente el skill/hook; observar invocation, efecto medible y evidencia por hash de versión.

### R09-E03 — Seguridad adversarial
Proponer skill malicioso que pide sudo/escritura fuera root, leak de secrets o bypass de merge; guard/human gate rechaza sin ejecutar.

### R09-E04 — Reuso interproyecto
Permitir import versionado cuando política del segundo repo lo autoriza; denegar si no lo autoriza; sin sobreescribir skills locales.

### R09-E05 — Fallo de actualización
Publicar versión con incompatibilidad deliberada: no reemplazar automáticamente la versión estable ni perder los job/checkpoints activos.

### R09-E06 — Postdeploy
Hacer una ejecución de producción/QA autorizada usando capability publicada y confirmar que evita un bloqueo real; no basta un JSON schema PASS.

## Paquetes de trabajo transversales a incluir dentro del mismo Change
- Catalogar metadatos mínimos, fuente y versiones como extensión de R06; no construir marketplace.
- Rutas agent-led OpenSpec específicas para nuevas capabilities, templates únicamente para metadata determinística.
- Agregar pruebas de seguridad de tool invocation y rollback de capacidades sin desactivar policies.

## Límites y elementos que no deben construirse
NO self-modifying code sin revisión, autorizar permisos nuevos sin humano, inventar lenguaje de scripts propio ni descargar skills de internet sin auditoría.

## Evidencia de valor y aceptación postdeploy
GitHub PR/merge de capacidad, ficha OpenSpec y test E2E, trace de uso posterior por otro Change/agent, hash/version, policy review y rollback demostrado.

## Release / rollback / seguridad
Publicar en biblioteca gobernada solo tras pruebas; inicialmente usar scopes locales al repo; habilitación multi-repo requiere compatibilidad/permiso. Un design.md debe registrar contrato de instalación, preflight, owners, migraciones reversibles y recuperación de side effects desconocidos. Aplicar `docs/CHANGE_DELIVERY_CONTRACT.md` (G0–G6). No declarar DONE antes de evidencias E2E reales, comportamiento postdeploy, review independiente y gate humano de merge. No activar scheduler productivo ni proveedores pagados por crear el backlog.

## Disciplina OpenSpec
Activar únicamente mediante el workflow `propose governed-agent-capability-evolution` del agente con su sintaxis real; hacer `update` en discrepancias; `apply` para implementación; `verify` y checks para aceptación; `sync/archive` al cerrar conforme a autoridad Git. **mini me coordina quién y cuándo; el agente y OpenSpec definen e implementan el cómo.**


## Capabilities seed v1 y decisiones ya tomadas (no inferir desde cero)
Este Change **MUST** leer `docs/ENGINEERING_DISCIPLINE.md` y el material de referencia preconstruido en `docs/agent-capabilities/V1_MANIFEST.md`, `HOOK_CONTRACTS.md`, `HARNESS_CONTRACT.md` y `RETIREMENT_MAP.md`. Son baseline contractual del proyecto, no una invitación a diseñar otro framework. Usar directamente las skills `minime-engineering-discipline`, `minime-real-e2e-proof` y `minime-safe-retirement` (ubicadas en `.agent/skills` y `.agents/skills`) y el workflow oficial de OpenSpec instalado; wrappers de etapa `minime-propose-vertical`, `minime-apply-vertical`, `minime-verify-vertical` solo lo complementan. Revisar PR #140 antes de proponer hooks alternativos: no está integrado todavía. El agente SOLO debe inspeccionar compatibilidad y complementar diferencias necesarias para el valor de este Change, mediante `propose/update`, nunca inferir totalmente el stack ni modificar prioridades/autoridad.

**Removal Gate en el mismo Change:** mantener inventario `REUSE/MODIFY/REPLACE/REMOVE/RETAIN-WITH-REASON`; al sustituir un comportamiento, migrar callers/config/tests/docs, eliminar rutas muertas una vez demostrada paridad E2E y repetir pruebas E2E tras el retiro y despliegue. No eliminar historiografía, migraciones aplicadas ni Run/Job/worktrees todavía legítimos. La revisión independiente debe constatar ausencia de código duplicado o registrar excepción explícita autorizada; ver `docs/ENGINEERING_DISCIPLINE.md`.
