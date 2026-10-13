# MM-R01 — real-openspec-agent-execution

**Estado:** PLANNED (no activo, no implementado). **Valor:** Primera entrega de código real con OpenSpec. **Predecesor:** baseline de seguridad. **E2E real + deploy:** obligatorios. **Merge humano:** obligatorio.

## Problema y resultado usable
La plataforma contiene adaptadores, WorktreeManager y orquestación, pero ninguna demostración aceptada y reproducible de un agente usando OpenSpec de forma nativa hasta un PR.

**Después del despliegue:** Desde un Change OpenSpec READY y un repositorio gestionado, mini me lanza un agente de IA real que aplica el workflow OpenSpec, ejecuta checks, coordina review independiente y publica un PR verificable; NO programa ni sintetiza la implementación.

## Contexto y contratos que debe leer el agente
docs/BUSINESS_INTENT.md; docs/ARCHITECTURE.md; docs/AGENT_CONTRACTS.md; docs/CHANGE_DELIVERY_CONTRACT.md; openspec/config.yaml; PR #152 (N01).. `docs/CHANGE_DELIVERY_CONTRACT.md` obliga a G0–G6, matriz de trazabilidad y gates E2E. El agente debe inspeccionar implementación actual, documentos, schema y skills instalados **antes de** proponer arquitectura; hechos heredados de ROADMAP “DELIVERED” deben verificarse.

## Specs mínimas obligatorias en el Change OpenSpec
Las siguientes capacidades deben materializarse como `openspec/changes/real-openspec-agent-execution/specs/<capability>/spec.md` (el agente decide agrupación razonable y resuelve design). No basta enumerarlas en `tasks.md`.

### R01-S01 — Admisión segura
SHALL aceptar un change READY vinculado duraderamente a (project_id, repo remoto verificado, Issue, change, base SHA). SHALL NOT permitir otra raíz de escritura ni inferir repositorio de título/Project.

### R01-S02 — Preflight sin cuota
SHALL verificar herramientas, versión/perfil de OpenSpec, skills/comandos instalados, permisos del worktree, base/head y acceso del agente; detectar auth/capacity con señales no inferentes. SHALL rechazar despacho si falta una condición de seguridad.

### R01-S03 — Workflow real de agente
SHALL lanzar la sintaxis de workflow apropiada dentro del CLI de Codex o Antigravity (skill/command instalado), no un ejecutable inexistente \`opsx\`. SHALL registrar transcript/handoff seguro, versión, invocation, tiempos y artefactos observados. El CLI \`openspec\` solamente valida/apoya artefactos según sus contratos.

### R01-S04 — Workspace/candidato
SHALL mantener trabajo dentro del worktree propio, registrar commit SHA y diff material, preservar side effects y exigir evidencia de autoría real; prohibido fake implementation/prompt de programador fuera de OpenSpec.

### R01-S05 — Verificación y revisión independiente
SHALL ejecutar checks del repo y workflow \`verify\` cuando esté disponible, exigir revisión por agente/modelo distinto del autor sustancial y aplicar correcciones con \`apply\` sobre el mismo Change cuando se autoricen. Fallos no generan PASS.

### R01-S06 — PR y autoridad humana
SHALL crear PR real desde candidate seguro con evidencia, enlace Issue/OpenSpec y checks. SHALL NOT hacer merge ni cerrar el trabajo por existencia del PR.

### R01-S07 — Preservación N01
SHALL preservar Run/Job original de N01, 4 attempts históricos, modificaciones OpenSpec y worktree CREATED. El Draft #152 es insumo a evaluar, no licencia para recrear, forzar CONTINUE o consumir cuota.

## E2E contractuales (Given / When / Then)
Los escenarios marcados E0x son la evidencia de producto requerida, nunca pruebas mock-only. **Dado** el entorno descrito; **cuando** se ejecuta el estímulo; **entonces** se observan el resultado y side effects correspondientes.

### R01-E01 — Ruta verde real
Dado repo fixture aislado + Change READY válidos, al admitir por la API real, mini me invoca un agente real con el workflow \`apply\`, modifica código dentro del WT, registra SHA, ejecuta checks, invoca revisor independiente y publica un PR inspeccionable en GitHub. Verificar deltas del código contra escenarios OpenSpec, no solo metadata.

### R01-E02 — Invocación nativa
Con perfil Codex y luego Antigravity en fixture autorizada, observar en los traces que se cargó el skill/workflow correcto. Una instrucción textual genérica o \`openspec validate\` **no** cuentan como ejecución \`apply\`.

### R01-E03 — Denegación previa
Inducir skill ausente, CLI desinstalado, auth inválida, cuota insuficiente, path escape y remote distinto; ninguna inferencia ni mutación externa ocurre y la UI/API informa motivo.

### R01-E04 — Fallo intermedio
Interrumpir el proceso tras un diff material y antes del PR; reiniciar y demostrar que el candidate/WT sobreviven y no aparece un segundo Job o branch inventado.

### R01-E05 — Independencia
Intentar asignar la misma identidad de modelo/agente a ejecución y revisión del mismo candidato; bloquear PR-ready y preservar evidencia.

### R01-E06 — N01 intacto
Antes/después comparar ids, historia, estado y archivos de N01. Si ejecutar N01 requiere credenciales/cuota no autorizadas, registrar WAITING y usar fixture E01 sin falsificar su recuperación.

### R01-E07 — Postdeploy
En servidor QA/despliegue autorizado, repetir una ejecución de bajo costo por el API/CLI reales y observar el PR y estados del destino. Health 200 sin PR NO pasa.

## Work packages incluidos en este mismo Change
- Rastrear exactamente los puntos de entrada en execution_pipeline.py, orchestration_service.py, implementer_runner.py, adapter OpenSpec y manager de worktrees; especificar *qué se conserva* y *qué se redirige* al skill del agente.
- Introducir contrato de invocación stage/workflow/proveedor, con manejo de salida normalizada, timeout, worktree, cancel/resume, versionado de tool y proof of tool use. Sin reimplementar apply.
- Definir una fixture pequeña, no el repositorio mini me como primer experimento destructivo; generar PR real desde base real, human merge obligatorio.
- Implementar verificaciones de regresión E2E desde el inicio y rollback sin pérdida de Run/Job.

## Exclusiones y guard de no-desviación
NO rediseñar todavía intake GitHub→propose, cierre posmerge completo, routing dinámico, dashboard cosmético ni auto-merge. No bloquear el primer PR esperando una plataforma genérica de skills.

## Evidencia exigida para marcar E2E_PASS y DEPLOYED_VERIFIED
Un PR de fixture creado realmente por mini me, un commit de código funcional, run/job/attempt con identidad real del agente y workflow OpenSpec, reviewer distinto, checks y E2E verificables, URLs y digest de despliegue, evidencia de preservación N01.

## Admisión, rollout y rollback
Scheduler productivo permanece desactivado; ejecución deliberadamente acotada en entorno aislado, preflight y autorización explícita para cada consumo real. PR y validación postdeploy antes de declarar entregado. El plan `design.md` deberá definir recuperación/rollback de código, migraciones y cambios de estado para este caso; si no es reversible, require gate humano explícito. El entregable pasa G1/G2/G3/G4/G5/G6 según `docs/CHANGE_DELIVERY_CONTRACT.md`; tests unitarios e integración son obligatorios pero no sustituyen E2E. No declarar DONE sin verificación del destino y cierre correspondiente.

## Ejecución sin prompts libres
Después de reconciliar contexto, activar SOLO este Change con el workflow `propose real-openspec-agent-execution` del **agente configurado** (sintaxis depende del proveedor); el agente debe crear todos los artefactos OpenSpec y confirmar escenarios E0x antes de `apply`. Las revisiones/ajustes son `update`, implementación `apply`, verificación `verify`; `sync/archive` cuando proceda. mini me coordina **etapas**, no emula las órdenes.
