# MM-R02 — intelligent-github-to-openspec-intake

**Estado:** PLANNED (no activo, no implementado). **Valor:** Del Issue a una propuesta OpenSpec coherente. **Predecesor:** MM-R01. **E2E real + deploy:** obligatorios. **Merge humano:** obligatorio.

## Problema y resultado usable
Intake produce proposal/specs/design/tasks por plantillas Python; pueden parecer listas sin que una IA haya razonado la intención, arquitectura ni criterios de aceptación.

**Después del despliegue:** Al crear una necesidad real en GitHub, mini me obtiene el contexto del proyecto y un agente utiliza `propose` para producir una propuesta multi-spec y DoR verificable; el operador no redacta artefactos ni prompts largos.

## Contexto y contratos que debe leer el agente
docs/GITHUB_WORK_MANAGEMENT.md; docs/DOR_DOD.md; docs/BACKLOG.md; Issue N03 #135; src/minime/services/intake_service.py; openspec_generator.py.. `docs/CHANGE_DELIVERY_CONTRACT.md` obliga a G0–G6, matriz de trazabilidad y gates E2E. El agente debe inspeccionar implementación actual, documentos, schema y skills instalados **antes de** proponer arquitectura; hechos heredados de ROADMAP “DELIVERED” deben verificarse.

## Specs mínimas obligatorias en el Change OpenSpec
Las siguientes capacidades deben materializarse como `openspec/changes/intelligent-github-to-openspec-intake/specs/<capability>/spec.md` (el agente decide agrupación razonable y resuelve design). No basta enumerarlas en `tasks.md`.

### R02-S01 — Idempotencia de Issue
SHALL tomar project_id, repo y Issue autorizado como identidad; deduplicar webhooks, reconciliar Issues repetidos, preservar historial y asociar un único Change activo por work item.

### R02-S02 — Context pack acotado
SHALL recopilar Business Intent, decisiones canónicas, arquitectura, OpenSpec config/specs existentes, conventions AGENTS/skills, dependencias y criterios, sin volcar secretos ni todo el repo.

### R02-S03 — Propuesta por IA y workflow
SHALL ejecutar `propose` del agente con contexto específico y descripción breve, obteniendo `proposal.md`, `design.md`, specs suficientes y `tasks.md`. No usar `OpenSpecGenerator` como autor ni convertir título del Issue en pseudo-arquitectura.

### R02-S04 — Calidad/anti-drift
SHALL contrastar propuesta con Business Intent, no duplicación de OpenSpec ni skills existentes; comprobar escenarios, trazabilidad, no-goals, plan E2E y evidencia. Una contradicción exige `update` agent-led.

### R02-S05 — Definition of Ready
SHALL marcar READY solo con artefactos reales validados, repo/issue binding, políticas de riesgo/costo, E2E y dependencias; ambigüedad material → pregunta humana persistida, no propuesta inventada.

### R02-S06 — Publicación durable
SHALL mantener propuesta en workspace con ownership y mecanismo de publicación idempotente, sin escribir prematuramente en main/managed root ni perder el change ante reinicios.

### R02-S07 — Migración
SHALL retirar o deshabilitar la ruta determinista solo después de probar la nueva ruta y conservar datos existentes; jamás destruir históricos ni reingestar N01 como nuevo.

## E2E contractuales (Given / When / Then)
Los escenarios marcados E0x son la evidencia de producto requerida, nunca pruebas mock-only. **Dado** el entorno descrito; **cuando** se ejecuta el estímulo; **entonces** se observan el resultado y side effects correspondientes.

### R02-E01 — Issue a propuesta real
Crear un Issue con necesidad funcional no trivial y criterios reales; mini me convoca Codex/AGY con `propose`, produce artefactos específicos del proyecto y status READY, con vínculo reversible.

### R02-E02 — Contradicción deliberada
Inyectar un Issue que pida mini me codificar directamente o auto-merge; el guard detecta contradicción canónica, el agente corrige o abre human gate, y no lo admite READY.

### R02-E03 — Ambigüedad de producto
Issue sin decisión material: NEEDS_HUMAN con pregunta y evidencia; respuesta autoriza `update` del mismo Change sin perder autoría ni crear duplicado.

### R02-E04 — Replay y caída
Repetir evento Issue y matar servicio tras publicación externa; se conserva un solo binding/change, misma saga y reconciliación sin nueva llamada a proveedor.

### R02-E05 — Contexto de segundo repo ficticio
Repo aislado con convenciones diferentes: artefactos respetan su propio AGENTS y no asumen estructura específica mini me.

### R02-E06 — Postdeploy
Crear Issue por la UI/API productiva bajo control, observar proposal multi-spec real generado por agente autorizado y consultar su DoR. Un template genérico es FAIL.

## Work packages incluidos en este mismo Change
- Redirigir IntakeService→OpenSpecGenerator hacia workflow agent-led; mantener validadores determinísticos y estado durable que sí son orquestación.
- Incluir matriz de capacidades/specs y E2E del Issue como entrada al agente; revisar invariantes de inmovilidad de managed roots.
- Definir retiro seguro de duplicados N01 #133/#138 como parte de reconciliación verificada, sin cerrar Issue equivocado.

## Exclusiones y guard de no-desviación
NO auto-admitir código en este Change (lo hará R03), no construir buscador/gestor de specs paralelo a OpenSpec, no limpiar históricos para satisfacer métricas.

## Evidencia exigida para marcar E2E_PASS y DEPLOYED_VERIFIED
URL del Issue real, identity binding, transcript de `propose`, propuesta/specs/design/tasks verificables y específicos, status de OpenSpec, prueba de no duplicidad y resultado postdeploy.

## Admisión, rollout y rollback
Preflight de cuota y autorización explícita antes de proponer; comenzar con repo QA e Issues de prueba limpios. No crear Issues nuevos por mera importación documental. El plan `design.md` deberá definir recuperación/rollback de código, migraciones y cambios de estado para este caso; si no es reversible, require gate humano explícito. El entregable pasa G1/G2/G3/G4/G5/G6 según `docs/CHANGE_DELIVERY_CONTRACT.md`; tests unitarios e integración son obligatorios pero no sustituyen E2E. No declarar DONE sin verificación del destino y cierre correspondiente.

## Ejecución sin prompts libres
Después de reconciliar contexto, activar SOLO este Change con el workflow `propose intelligent-github-to-openspec-intake` del **agente configurado** (sintaxis depende del proveedor); el agente debe crear todos los artefactos OpenSpec y confirmar escenarios E0x antes de `apply`. Las revisiones/ajustes son `update`, implementación `apply`, verificación `verify`; `sync/archive` cuando proceda. mini me coordina **etapas**, no emula las órdenes.
