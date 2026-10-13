# MM-R10 — autonomous-self-development

**Estado:** PLANNED (no activo). **Dependencias:** MM-R01–MM-R09. **Capacidad entregada:** mini me desarrolla mini me y entrega valor recurrente.

## Business intent: problema → resultado real
**Antes:** mini me aún requiere dirección humana de cada etapa y carece de una prueba integral de autodesarrollo; múltiples milestones técnicos no equivalen a autonomía productiva.

**Después de desplegar:** Desde una mejora priorizada del propio backlog, mini me produce sus artefactos con OpenSpec y agentes, cambia su código, prueba, revisa, entrega PR, espera merge humano, despliega/verifica y continúa con el siguiente item elegible.

## Requisitos por spec (se implementan en un Change OpenSpec multi-spec)
Los Sxx son mínimos normativos. En `propose`, el agente clasifica las specs por comportamiento/capacidad, formula SHALL/SHALL NOT y escenarios Given/When/Then, resuelve tradeoffs en design, y crea tasks ordenadas incluyendo pruebas reales. No iniciar `apply` sin trazar todos los requisitos contra evidencia final y revisar no-goals.

### R10-S01 — Self binding
SHALL seleccionar su repositorio y Issue desde binding durable, evitar self-override de políticas, proteger production worktree/runtime/DB y prohibir escribir directamente al proceso en ejecución.

### R10-S02 — Queue self-service
SHALL seleccionar un backlog item apto, verificar dependencias/DoR/capacidad y crear OpenSpec mediante agent-led `propose` con contexto Business Intent; no inventar funcionalidades ni ejecutar Changes fuera del backlog.

### R10-S03 — Desarrollo completo
SHALL recorrer `apply/verify/review/remediation` con Codex/Antigravity según políticas de etapa y roles separados, producir PR real con pruebas E2E; ningún agente autoaprueba su propio cambio.

### R10-S04 — Aprendizaje verificable
SHALL medir primera pasada, regresiones, fallos/cuota, recuperación, tiempo a PR, E2E productivo y causas reales; solo proponer mejoras a políticas con cambios OpenSpec/human gate, no autooptimización opaca.

### R10-S05 — Cierre protegido
SHALL observar merge humano, ejecutar workflows nativos de `sync/archive`, despliegue inmutable/rollback y pruebas funcionales en servidor real; al reiniciar, self-service sigue en estado consistente.

### R10-S06 — Autonomía real
SHALL pasar automáticamente a siguiente trabajo sin clics innecesarios, con cancel/pausa humana, backpressure por cuotas y visibilidad móvil/tablet/web; bloquear si no hay capacidad o una decisión legítima.

### R10-S07 — Auto-reparación limitada
SHALL diagnosticar defectos de plataforma e iniciar solo los Changes autorizados; nunca editar su scheduler/auth/guards en ejecución ni rebajar gates bajo presión.

### R10-S08 — Seguridad anti-recursión
SHALL diferenciar control-plane en marcha del código candidate, no desplazar su propio control durante una job, impedir ejecuciones recursivas que creen infinitos backlog/PR.

### R10-S09 — Métricas de producto
SHALL mostrar cambios útiles efectivamente entregados, E2E postdeploy, tasa de reintento y tiempo de intervención humana, sin métricas vanity por cantidad de pruebas.

### R10-S10 — Autodesarrollo reproducible
SHALL permitir restaurar desde versión desplegada y reconstruir la historia completa de spec→workflow→agent→SHA→PR→merge→deploy, sin acceso al Mac.

## Escenarios E2E de etapa, Change y destino
Cada E0x es contractual y debe tener setup, ejecución, verificaciones de side effects y evidencias durables. Test mock-only no satisface un escenario que atribuye una acción a un agente/servicio real; un E2E no corrido es `BLOCKED` o `NOT VERIFIED`.

### R10-E01 — Self-feature real
Crear una necesidad pequeña de mini me con criterio visible en UI/API, no generada artificialmente por el test; el sistema desarrolla la mejora mediante OpenSpec, produce PR revisado y el humano decide merge.

### R10-E02 — Lifecycle completo
Tras merge humano, mini me publica nuevo artefacto, despliega con rollback, ejecuta E2E del comportamiento en URL real y archiva/reconcilia GitHub; ningún paso humano salvo gates legítimos.

### R10-E03 — Próxima tarea
Con 2 items READY, finalizado el primero el scheduler considera automáticamente el segundo, respeta dependencia/quota y no necesita click Start.

### R10-E04 — Reinicio entre deploy y persist
Matar servicio entre cambio productivo/ack: recuperación observa estado del artefacto, no se redespliega a ciegas ni pierde evidencia.

### R10-E05 — Propuesta peligrosamente incorrecta
Un Change auto-originado propone auto-merge o desactivar seguridad; guard de Business Intent bloquea y conserva control humano.

### R10-E06 — Quota dual exhausted
Sin capacidad Codex/AGY ni fallback autorizado, deja todo en WAIT sin gasto, explica el bloqueo y retoma automáticamente cuando señal confiable lo permite.

### R10-E07 — Operador a distancia
Desde móvil observar qué hace/qué hizo/qué viene y un gate humano; desde tablet/web decidir el PR/validación dentro de sus permisos.

### R10-E08 — Regresión de todo lo entregado
Después del self-update correr smoke funcional R01–R09 (adaptable al riesgo) y E2E postdeploy de nueva capacidad; si falla, rollback y estado no DONE.

## Paquetes de trabajo transversales a incluir dentro del mismo Change
- Utilizar exclusivamente el pipeline madurado en R01–R09, no introducir un segundo self-coder.
- Agregar límites de autorreparación, gestión de self runtime y lectura de resultados de valor, con regresión funcional.
- Demostrar una mejora real y no artificial con evidencia de usuario; la automatización de selección no cambia autoridad del merge.

## Límites y elementos que no deben construirse
NO auto-merge, self-awarded budgets, regeneración indiscriminada de backlog, mutación directa de producción por agente, benchmark infinito, utilización de IA como sustituto de OpenSpec.

## Evidencia de valor y aceptación postdeploy
Issue real→spec OpenSpec agent-led→diff de mini me→checks/review independiente→PR→human merge→deployment digest→feature observable en servidor→archive/GitHub DONE→siguiente item considered, con traces y costo autorizado.

## Release / rollback / seguridad
Requiere release de R01–R09 y backup/rollback probados, code signing/artifact identity donde aplique; el operador habilita self-development con interruptor de emergencia y límites, sin quitar human merge. Un design.md debe registrar contrato de instalación, preflight, owners, migraciones reversibles y recuperación de side effects desconocidos. Aplicar `docs/CHANGE_DELIVERY_CONTRACT.md` (G0–G6). No declarar DONE antes de evidencias E2E reales, comportamiento postdeploy, review independiente y gate humano de merge. No activar scheduler productivo ni proveedores pagados por crear el backlog.

## Disciplina OpenSpec
Activar únicamente mediante el workflow `propose autonomous-self-development` del agente con su sintaxis real; hacer `update` en discrepancias; `apply` para implementación; `verify` y checks para aceptación; `sync/archive` al cerrar conforme a autoridad Git. **mini me coordina quién y cuándo; el agente y OpenSpec definen e implementan el cómo.**


## Capabilities seed v1 y decisiones ya tomadas (no inferir desde cero)
Este Change **MUST** leer `docs/ENGINEERING_DISCIPLINE.md` y el material de referencia preconstruido en `docs/agent-capabilities/V1_MANIFEST.md`, `HOOK_CONTRACTS.md`, `HARNESS_CONTRACT.md` y `RETIREMENT_MAP.md`. Son baseline contractual del proyecto, no una invitación a diseñar otro framework. Usar directamente las skills `minime-engineering-discipline`, `minime-real-e2e-proof` y `minime-safe-retirement` (ubicadas en `.agent/skills` y `.agents/skills`) y el workflow oficial de OpenSpec instalado; wrappers de etapa `minime-propose-vertical`, `minime-apply-vertical`, `minime-verify-vertical` solo lo complementan. Revisar PR #140 antes de proponer hooks alternativos: no está integrado todavía. El agente SOLO debe inspeccionar compatibilidad y complementar diferencias necesarias para el valor de este Change, mediante `propose/update`, nunca inferir totalmente el stack ni modificar prioridades/autoridad.

**Removal Gate en el mismo Change:** mantener inventario `REUSE/MODIFY/REPLACE/REMOVE/RETAIN-WITH-REASON`; al sustituir un comportamiento, migrar callers/config/tests/docs, eliminar rutas muertas una vez demostrada paridad E2E y repetir pruebas E2E tras el retiro y despliegue. No eliminar historiografía, migraciones aplicadas ni Run/Job/worktrees todavía legítimos. La revisión independiente debe constatar ausencia de código duplicado o registrar excepción explícita autorizada; ver `docs/ENGINEERING_DISCIPLINE.md`.
