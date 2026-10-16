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
SHALL verificar herramientas, versión/perfil de OpenSpec, skills/comandos instalados, permisos del worktree, base/head, acceso, autorización y capacidad del agente seleccionado. SHALL validar, por etapa (PLAN, CONTRACT REVIEW, APPLY, TEST, VERIFY/E2E y REVIEW), proveedor, modelo y esfuerzo configurados contra el CLI/version/workflow realmente instalado; compatibilidad ausente o desconocida bloquea el despacho. Seleccionará el perfil configurado de menor coste que satisfaga requisitos documentados de complejidad/riesgo y capacidad. Modelos premium y esfuerzo máximo no serán defaults. Cualquier escalamiento requerirá evidencia objetiva, razón persistida, límite finito y autorización de presupuesto. No habrá optimización dinámica ni selector/scheduler paralelo en R01.

### R01-S03 — Workflow real de agente
SHALL seleccionar Codex o Antigravity como planner/ejecutor primario por perfil stage-specific, compatibilidad, capacidad y presupuesto; un relevo compatible preserva Run/Job, worktree, checkpoints, fences y efectos idempotentes. DeepSeek Direct es el revisor read-only obligatorio de CONTRACT REVIEW y code REVIEW como etapas/evidencias distintas, con cuenta, capacidad, precio, autorización y reserva propias; si una revisión requerida no es elegible, el trabajo espera sin sustitución. DeepSeek no planifica, implementa ni rescata. OpenRouter solo puede rescatar trabajo iniciado cuando ambos primarios están bloqueados por cuota, con su propia capacidad y presupuesto; nunca revisa ni admite trabajo nuevo. Ninguna revisión autoriza APPLY o merge. Cada agente ejecutará su workflow nativo instalado con sintaxis observada, no un ejecutable `opsx` supuesto. SHALL registrar identidad/modelo/esfuerzo, perfil, versión, invocación, tiempos y artefactos observados. El CLI `openspec` solo valida/apoya artefactos según sus contratos.

### R01-S04 — Workspace/candidato
SHALL mantener trabajo dentro del worktree propio, registrar commit SHA y diff material, preservar side effects y exigir evidencia de autoría real; prohibido fake implementation/prompt de programador fuera de OpenSpec.

### R01-S05 — Verificación y revisión independiente
SHALL ejecutar las pruebas de implementación bajo el perfil TEST aprobado y VERIFY/E2E con Codex contra el candidato congelado. La ausencia/incompatibilidad/capacidad desconocida de Codex SHALL dejar el trabajo esperando, nunca omitir VERIFY. La revisión de contrato será read-only y no autorizará APPLY ni decisiones de producto. La revisión final del código exigirá identidad distinta de todo autor sustancial superviviente y seguirá la política final vigente. Fallos no generan PASS. IA local es opcional y auxiliar; nunca diagnostica fallos, implementa, revisa seguridad o decide de forma vinculante, y su ausencia no bloquea.

### R01-S06 — PR y autoridad humana
SHALL crear PR real desde candidate seguro con evidencia, enlace Issue/OpenSpec y checks. SHALL NOT hacer merge ni cerrar el trabajo por existencia del PR.

### R01-S07 — Preservación N01
SHALL preservar Run/Job original de N01, 4 attempts históricos, modificaciones OpenSpec y worktree CREATED. El Draft #152 es insumo a evaluar, no licencia para recrear, forzar CONTINUE o consumir cuota.

## E2E contractuales (Given / When / Then)
Los escenarios marcados E0x son la evidencia de producto requerida, nunca pruebas mock-only. **Dado** el entorno descrito; **cuando** se ejecuta el estímulo; **entonces** se observan el resultado y side effects correspondientes.

### R01-E01 — Ruta verde real
Dado repo fixture aislado + Change READY válidos y perfiles stage válidos, al admitir por la API real mini me aplica PLAN/CONTRACT REVIEW/APPLY/TEST/VERIFY/E2E/REVIEW con los roles autorizados y realmente compatibles, modifica código solo en el WT, registra SHA, ejecuta checks, obtiene revisión final independiente y publica un PR inspeccionable. El gate de contrato no autoriza APPLY y la revisión final no autoriza merge. Verificar deltas del código contra escenarios OpenSpec, no solo metadata.

### R01-E02 — Invocación nativa
Con AGY en APPLY y Codex en PLAN/VERIFY-E2E sobre fixture autorizada, observar en trazas que cada CLI cargó el workflow nativo correcto y que modelo/esfuerzo son admitidos por esa versión. Una instrucción textual genérica o `openspec validate` **no** cuentan como ejecución `apply`.

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
- Extender la configuración de etapa y el resolver/autoridades existentes para perfiles independientes de provider/model/effort; validar capacidades reales del CLI/version, registrar selección y autorización, aplicar menor coste suficiente y rechazar escalamiento sin evidencia, límite y presupuesto aprobados. No agregar selector/scheduler paralelo ni optimizador dinámico.
- Introducir contrato de invocación stage/workflow/proveedor, con manejo de salida normalizada, timeout, worktree, cancel/resume, versionado de tool y proof of tool use. Codex y AGY pueden planificar/ejecutar etapas compatibles por perfil y capacidad, con relevo durable seguro. DeepSeek Direct realiza CONTRACT REVIEW y final code REVIEW read-only como etapas separadas; no hay sustitución si falta autoridad. OpenRouter es rescate de ejecución para trabajo iniciado después de agotamiento de cuota de ambos primarios, nunca reviewer ni admisor de trabajo nuevo. Sin reimplementar workflows.
- Mantener IA local opcional y no bloqueante para clasificación preliminar de complejidad, preparación/reducción de contexto, extracción, etiquetas y tareas auxiliares; nunca diagnóstico, implementación autoritativa, revisión de seguridad o decisión vinculante.
- Definir una fixture pequeña, no el repositorio mini me como primer experimento destructivo; generar PR real desde base real, human merge obligatorio.
- Implementar verificaciones de regresión E2E desde el inicio y rollback sin pérdida de Run/Job.

## Exclusiones y guard de no-desviación
NO rediseñar todavía intake GitHub→propose, cierre posmerge completo, optimización dinámica de selección, benchmarking/auto-aprendizaje de perfiles, plataforma genérica de skills, dashboard cosmético ni auto-merge. R01 incluye únicamente configuración estática por etapa, validación de capacidades reales, aplicación de la asignación aprobada y escalamiento gobernado por evidencia/presupuesto; los optimizadores, clasificación automática vinculante y selección predictiva quedan para Changes posteriores. No bloquear un flujo por la indisponibilidad de IA local.

## Evidencia exigida para marcar E2E_PASS y DEPLOYED_VERIFIED
Un PR de fixture creado realmente por mini me, un commit de código funcional, run/job/attempt con identidad real del agente y workflow OpenSpec, reviewer distinto, checks y E2E verificables, URLs y digest de despliegue, evidencia de preservación N01.

## Admisión, rollout y rollback
Scheduler productivo permanece desactivado; ejecución deliberadamente acotada en entorno aislado, preflight y autorización explícita para cada consumo real. PR y validación postdeploy antes de declarar entregado. El plan `design.md` deberá definir recuperación/rollback de código, migraciones y cambios de estado para este caso; si no es reversible, require gate humano explícito. El entregable pasa G1/G2/G3/G4/G5/G6 según `docs/CHANGE_DELIVERY_CONTRACT.md`; tests unitarios e integración son obligatorios pero no sustituyen E2E. No declarar DONE sin verificación del destino y cierre correspondiente.

## Ejecución sin prompts libres
Después de reconciliar contexto, activar SOLO este Change con el workflow `propose real-openspec-agent-execution` del **agente configurado** (sintaxis depende del proveedor); el agente debe crear todos los artefactos OpenSpec y confirmar escenarios E0x antes de `apply`. Las revisiones/ajustes son `update`, implementación `apply`, verificación `verify`; `sync/archive` cuando proceda. mini me coordina **etapas**, no emula las órdenes.


## Handoff preconstruido específico de R01

**Antes de `propose` leer `docs/agent-capabilities/R01_IMPLEMENTATION_STARTER.md`.** Contiene censo inicial de los entrypoints del repositorio, responsabilidades que no se pueden cambiar, diseño de interfaces de etapa, fixture E2E real, política de N01 y plan de retiro; el agente valida estas hipótesis contra el código y solo complementa diferencias verificadas, dentro de OpenSpec.

## Capabilities seed v1 y decisiones ya tomadas (no inferir desde cero)
Este Change **MUST** leer `docs/ENGINEERING_DISCIPLINE.md` y el material de referencia preconstruido en `docs/agent-capabilities/V1_MANIFEST.md`, `HOOK_CONTRACTS.md`, `HARNESS_CONTRACT.md` y `RETIREMENT_MAP.md`. Son baseline contractual del proyecto, no una invitación a diseñar otro framework. Usar directamente las skills `minime-engineering-discipline`, `minime-real-e2e-proof` y `minime-safe-retirement` (ubicadas en `.agent/skills` y `.agents/skills`) y el workflow oficial de OpenSpec instalado; wrappers de etapa `minime-propose-vertical`, `minime-apply-vertical`, `minime-verify-vertical` solo lo complementan. Revisar PR #140 antes de proponer hooks alternativos: no está integrado todavía. El agente SOLO debe inspeccionar compatibilidad y complementar diferencias necesarias para el valor de este Change, mediante `propose/update`, nunca inferir totalmente el stack ni modificar prioridades/autoridad.

**Removal Gate en el mismo Change:** mantener inventario `REUSE/MODIFY/REPLACE/REMOVE/RETAIN-WITH-REASON`; al sustituir un comportamiento, migrar callers/config/tests/docs, eliminar rutas muertas una vez demostrada paridad E2E y repetir pruebas E2E tras el retiro y despliegue. No eliminar historiografía, migraciones aplicadas ni Run/Job/worktrees todavía legítimos. La revisión independiente debe constatar ausencia de código duplicado o registrar excepción explícita autorizada; ver `docs/ENGINEERING_DISCIPLINE.md`.
