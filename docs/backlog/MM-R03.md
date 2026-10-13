# MM-R03 — autonomous-backlog-to-reviewed-pr

**Estado:** PLANNED (no activo, no implementado). **Valor:** Ejecución autónoma de un backlog hasta PR revisado. **Predecesor:** MM-R01 + MM-R02. **E2E real + deploy:** obligatorios. **Merge humano:** obligatorio.

## Problema y resultado usable
Existe lógica de scheduler/orquestación y numerosos estados, pero falta demostración de autodrain de una cola con agente OpenSpec real y entregable PR.

**Después del despliegue:** Un Issue preparado y READY avanza por selección, `apply`, `verify`, review independiente y PR sin clics manuales Prepare/Start/Continue; solo pausa por política/cuota/autoridad humana legítima.

## Contexto y contratos que debe leer el agente
docs/STATE_MACHINE.md; docs/DOR_DOD.md; docs/GITHUB_WORK_MANAGEMENT.md; docs/CHANGE_DELIVERY_CONTRACT.md; tests/postgres scheduler; issues #133/#135.. `docs/CHANGE_DELIVERY_CONTRACT.md` obliga a G0–G6, matriz de trazabilidad y gates E2E. El agente debe inspeccionar implementación actual, documentos, schema y skills instalados **antes de** proponer arquitectura; hechos heredados de ROADMAP “DELIVERED” deben verificarse.

## Specs mínimas obligatorias en el Change OpenSpec
Las siguientes capacidades deben materializarse como `openspec/changes/autonomous-backlog-to-reviewed-pr/specs/<capability>/spec.md` (el agente decide agrupación razonable y resuelve design). No basta enumerarlas en `tasks.md`.

### R03-S01 — Plan y dependencias
SHALL descubrir/ordenar work items READY de GitHub y DB con prioridades y DAG, cumplir predecesores/quotas/concurrency; registrar por qué cada item fue seleccionado o diferido.

### R03-S02 — Auto-preparación/admisión
SHALL pasar de Issue preparado a Job admitido sin botones manuales cuando DoR, permisos, provider y presupuesto lo permiten. No fabricar contexto ni sobrescribir worktrees ajenos.

### R03-S03 — Stages OpenSpec
SHALL asignar `propose/update/continue/apply/verify` al agente compatible por etapa y comprobar salida real; no usar prompts libres como sustituto de workflows. Reviewer no puede compartir identidad de autoría.

### R03-S04 — Durabilidad
SHALL preservar eventos, claim, generation y side effects de etapa; toda reanudación inspecciona estado remoto/local antes de reenviar. Como mínimo una ejecución activa por repositorio según política.

### R03-S05 — Gates y corrección
SHALL hacer checks y revisión, corregir solo con evidencia nueva y retries limitados, bloquear desviación, no aceptar auto-auditoría ni suplantar juicio humano.

### R03-S06 — Final observable
SHALL crear PR Draft con contexto/proposal, links al Issue, diff/checks/evidencias reales y estado Human Review. El merge está reservado al humano.

### R03-S07 — Vista operador
SHALL mostrar etapa actual, qué hizo, próximo paso, espera/costo y causas en API/PWA existente con lecturas del mismo Run/Job; sin exigir acceso a DB.

## E2E contractuales (Given / When / Then)
Los escenarios marcados E0x son la evidencia de producto requerida, nunca pruebas mock-only. **Dado** el entorno descrito; **cuando** se ejecuta el estímulo; **entonces** se observan el resultado y side effects correspondientes.

### R03-E01 — Cola completa
Con dos Issues independientes y un Issue dependiente en QA, los READY autónomamente generan artefactos OpenSpec y PRs reales en orden admisible; el dependiente no comienza antes del gate configurado.

### R03-E02 — Cero handoffs
Después de crear/admitir el Issue no se permiten comandos ni clics de operador para mover stages no humanos; verificar logs de acciones y no solo tiempo de ejecución.

### R03-E03 — Capacidad heterogénea
Con uno de los agentes no disponible, implementar únicamente rutas/revisiones permitidas y esperar si falta reviewer independiente; no admitir ruta insegura por urgencia.

### R03-E04 — Reinicio/scheduler
Interrumpir daemon entre stage/side effect y persistencia: no Issues, PRs, branches, Jobs ni dispatch duplicados; el trabajo preservado converge al estado verificable.

### R03-E05 — Revisión rechazada
Inyectar un defecto en la implementación; revisor lo detecta, la remediación por `apply` corrige y `verify` real valida, o queda bloqueado con hallazgos sin PR-ready.

### R03-E06 — Postdeploy
Scheduler habilitado SOLO en ventana autorizada de QA: captura de selección desde cola real hasta PR, estado observable por aplicación y no side effects no autorizados.

## Work packages incluidos en este mismo Change
- Unificar flujo de intake y ejecución existente sin un orquestador paralelo; reutilizar sagas, claims, scheduler, PR service y evidence store.
- Reconciliar gates DeepSeek hard-coded que violan fallback-only; no introducir una auditoría extra obligatoria contra la política vigente.
- Conservar N01 histórico y resolver estados AUTH_REQUIRED/WAITING mediante rutas durables, no sobrescribirlo por fixture.

## Exclusiones y guard de no-desviación
NO auto-merge, no desplegar producción automáticamente, no prometer continuidad 24/7 o IQ de enrutamiento que no existe. Cierre postmerge es R04.

## Evidencia exigida para marcar E2E_PASS y DEPLOYED_VERIFIED
GitHub Issue/PR reales por item, 2+ cambios bajo plan, elección explicada, author/reviewer distintos, workflow traces, checks y defect/remediation E2E, paso al human gate visible postdeploy.

## Admisión, rollout y rollback
Ejecutar primero sobre fixtures y una ventana controlada, con scheduler prod desactivado hasta autorización y E2E previo. En producción admitir solo el scope autorizado. El plan `design.md` deberá definir recuperación/rollback de código, migraciones y cambios de estado para este caso; si no es reversible, require gate humano explícito. El entregable pasa G1/G2/G3/G4/G5/G6 según `docs/CHANGE_DELIVERY_CONTRACT.md`; tests unitarios e integración son obligatorios pero no sustituyen E2E. No declarar DONE sin verificación del destino y cierre correspondiente.

## Ejecución sin prompts libres
Después de reconciliar contexto, activar SOLO este Change con el workflow `propose autonomous-backlog-to-reviewed-pr` del **agente configurado** (sintaxis depende del proveedor); el agente debe crear todos los artefactos OpenSpec y confirmar escenarios E0x antes de `apply`. Las revisiones/ajustes son `update`, implementación `apply`, verificación `verify`; `sync/archive` cuando proceda. mini me coordina **etapas**, no emula las órdenes.


## Capabilities seed v1 y decisiones ya tomadas (no inferir desde cero)
Este Change **MUST** leer `docs/ENGINEERING_DISCIPLINE.md` y el material de referencia preconstruido en `docs/agent-capabilities/V1_MANIFEST.md`, `HOOK_CONTRACTS.md`, `HARNESS_CONTRACT.md` y `RETIREMENT_MAP.md`. Son baseline contractual del proyecto, no una invitación a diseñar otro framework. Usar directamente las skills `minime-engineering-discipline`, `minime-real-e2e-proof` y `minime-safe-retirement` (ubicadas en `.agent/skills` y `.agents/skills`) y el workflow oficial de OpenSpec instalado; wrappers de etapa `minime-propose-vertical`, `minime-apply-vertical`, `minime-verify-vertical` solo lo complementan. Revisar PR #140 antes de proponer hooks alternativos: no está integrado todavía. El agente SOLO debe inspeccionar compatibilidad y complementar diferencias necesarias para el valor de este Change, mediante `propose/update`, nunca inferir totalmente el stack ni modificar prioridades/autoridad.

**Removal Gate en el mismo Change:** mantener inventario `REUSE/MODIFY/REPLACE/REMOVE/RETAIN-WITH-REASON`; al sustituir un comportamiento, migrar callers/config/tests/docs, eliminar rutas muertas una vez demostrada paridad E2E y repetir pruebas E2E tras el retiro y despliegue. No eliminar historiografía, migraciones aplicadas ni Run/Job/worktrees todavía legítimos. La revisión independiente debe constatar ausencia de código duplicado o registrar excepción explícita autorizada; ver `docs/ENGINEERING_DISCIPLINE.md`.
