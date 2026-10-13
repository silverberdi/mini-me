# mini me — backlog de recuperación orientado a valor (propuesto)

> **Estado:** plan propuesto; NO equivale a código implementado ni prueba productiva. Aprobación de este PR actualiza la **planificación**, no autoriza por sí sola consumo de agentes, migraciones, merge de otros PR, despliegue ni activación del scheduler.
>
> **Autoridad:** `docs/BUSINESS_INTENT.md` → `docs/CANONICAL_DECISIONS.md` → `docs/PRODUCT.md` → `docs/CHANGE_DELIVERY_CONTRACT.md` → OpenSpec vigente por Change. Ante contradicción, detener `propose`/`apply`, documentar discrepancia y resolverla en el Change; jamás inventar reglas alternativas.

## Objetivo y definición del valor

mini me coordina **agentes de IA que usan OpenSpec**; no es una IA programadora, un generador propio de artefactos SDD ni un reemplazo de los workflows OpenSpec. El valor es que el dueño registre trabajo y mini me seleccione agentes y capacidades, prepare contexto autorizado, gobierne etapas/cuotas/seguridad, preserve progreso y produzca software revisado hasta PR y cierre tras merge humano. GitHub conserva la cartera; OpenSpec es autoridad sobre comportamiento y planificación; PostgreSQL sobre ejecución y evidencia; Git sobre código e identidades de candidatos.

Cada Change agrupa **todas** las specs backend/frontend/persistencia/CLI/harness/seguridad necesarias para entregar una capacidad operativa completa. Está prohibido dividir una capacidad en fases técnicas que no entreguen utilidad. Todas las comprobaciones pasan por E2E real de la etapa y del resultado desplegado, según `docs/CHANGE_DELIVERY_CONTRACT.md`.

## Orden de entrega aprobado para elaboración (dependencias por capacidad)

| ID | Change OpenSpec (slug) | Entrega observable | Depende de | Ficha |
|---|---|---|---|---|
| MM-R01 | `real-openspec-agent-execution` | Un OpenSpec READY es implementado mediante el workflow de un agente real, revisado por otro y entregado en PR | Baseline segura | [Ficha](backlog/MM-R01.md) |
| MM-R02 | `intelligent-github-to-openspec-intake` | Issue real → propuesta OpenSpec coherente creada por IA, con trazabilidad y DoR | R01 | [Ficha](backlog/MM-R02.md) |
| MM-R03 | `autonomous-backlog-to-reviewed-pr` | Work item admitido → propuesta, ejecución y PR revisado sin handoffs manuales | R01–R02 | [Ficha](backlog/MM-R03.md) |
| MM-R04 | `native-openspec-delivery-and-closure` | Merge humano → workflows nativos `sync/archive`, despliegue autorizado y DONE íntegro | R03 | [Ficha](backlog/MM-R04.md) |
| MM-R05 | `quota-safe-execution-and-recovery` | Espera/reanudación automática segura ante cuota, autenticación, reinicio o fallo | R03–R04; garantías mínimas desde R01 | [Ficha](backlog/MM-R05.md) |
| MM-R06 | `project-aware-agent-capabilities` | Agentes usan skills/hooks/commands/guards/harnesses adecuados en un cambio real | R05; capacidades esenciales desde R01 | [Ficha](backlog/MM-R06.md) |
| MM-R07 | `operational-control-and-human-attention` | UI explica estado/causas/siguiente paso y resuelve gates humanos reales | R03–R06 | [Ficha](backlog/MM-R07.md) |
| MM-R08 | `multi-repository-sdd-execution` | Un segundo repo completa E2E respetando su propia metodología y bindings | R01–R07 | [Ficha](backlog/MM-R08.md) |
| MM-R09 | `governed-agent-capability-evolution` | Skills/hooks/harnesses faltantes evolucionan vía OpenSpec y revisión humana | R06–R08 | [Ficha](backlog/MM-R09.md) |
| MM-R10 | `autonomous-self-development` | mini me selecciona y desarrolla una mejora de mini me con PR/merge/closure verificable | R01–R09 | [Ficha](backlog/MM-R10.md) |

**Política de dependencias:** no hay prerrequisito de “terminar todos los mecanismos técnicos” antes de obtener el valor del primer Change. Cada Change debe implementar la porción vertical mínima completa, incluyendo seguridad, preflight, E2E, observabilidad y rollback aplicables. Cambios futuros amplían sin dejar rotas las garantías existentes. Reordenar únicamente por decisión explícita que preserve dichas garantías.

## Reconciliación conservadora del backlog anterior

- `docs/ROADMAP.md` anterior declaraba 001–021/018.* “DELIVERED”. Son **hitos históricos de implementación**, no evidencias suficientes del objetivo final. Se conserva su historial Git/PR/OpenSpec; su funcionalidad debe ser revalidada como parte de los E2E verticales.
- Issues activos [#133](https://github.com/silverberdi/mini-me/issues/133) y [#138](https://github.com/silverberdi/mini-me/issues/138): ambas entradas refieren a N01; no crear otro N01. Mantener identidades/historial; decidir canon y retiro del duplicado mediante reconciliación idempotente antes de cambiar Issues/DB.
- N01 no se puede recrear ni borrar: conservar Run/Job, workspace CREATED, intentos, modificados, eventos, ownership y acciones externas. [PR #152](https://github.com/silverberdi/mini-me/pull/152) permanece Draft y debe evaluarse como posible insumo R01/R05, no declararse cierre.
- Issues [#134](https://github.com/silverberdi/mini-me/issues/134), [#135](https://github.com/silverberdi/mini-me/issues/135), [#136](https://github.com/silverberdi/mini-me/issues/136), [#137](https://github.com/silverberdi/mini-me/issues/137): conservar alcance útil como escenarios de R07 (N02/N04/N05) y gobernanza de reconciliación de R02/R03 (N03). No ejecutar los cinco como un roadmap paralelo.
- [PR #140](https://github.com/silverberdi/mini-me/pull/140): hooks de calidad todavía no fusionados. Auditar integración/invariantes con R01/R06/R09 antes de reutilizarlos, sin duplicar su trabajo.
- Issues históricos ya cerrados sobre routing local, Qwen, telemetry, grafos, UX y harnesses: **no reabrir automáticamente**; reutilizar únicamente lo demostrado necesario por el Change vigente. Prohibido introducir benchmarking/analítica/estética como prerequisito de una primera entrega real.
- OpenSpec `changes/archive/`, documentación pasada y eventos de producción son **historial inmutable**, no “basura” para limpiar. Nunca migrar o declarar DONE artificialmente para cuadrar métricas.
- La herramienta GitHub conectada no expone aquí una API de GitHub Projects v2; la reconciliación de campos/cards del Project requiere un ejecutor autorizado capaz de verificarla. **No suponer que cambiar estos archivos sincroniza el Project ni PostgreSQL.**

## Regla de planificación OpenSpec

Estas fichas son **contratos de backlog**, no `proposal.md` ni `specs/` artificiales. Solamente un Change activo se convierte mediante el workflow `propose` del **agente** en `openspec/changes/<slug>/`. En la propuesta se materializan todas las specs funcionales y escenarios de la ficha, con verificación de consistencia. `apply` y `verify` ocurren mediante los workflows instalados en el agente correspondiente, bajo los guards del proyecto. No emitir prompts libres fuera de ese circuito.

Los nombres e invocaciones son **específicos por agente**: Codex usa skills `$openspec-propose` / `$openspec-apply` si están instalados; otros agentes pueden usar `/opsx-propose` o `/opsx:propose`. Son invocaciones en el **agente**, no binarios de shell `opsx`. El CLI `openspec` puede proporcionar `new`, `status`, `instructions`, `validate` y `archive` conforme a versión instalada. mini me jamás simulará una llamada al workflow invocando un script Python que replique su semántica.

## Primera admisión

1. Scheduler productivo permanece **disabled/inactive** hasta E2E autorizado, capacidad verificable y release gate cumplido.
2. Obtener baseline `main`, estado real de PR #140/#152 y del N01, binding exacto, política de cuota, configuración de OpenSpec y compatibilidad CLI/harness.
3. Abrir con un agente autorizado `propose real-openspec-agent-execution` usando solo esta ficha y contexto canónico. Exigir a OpenSpec la propuesta multi-spec y pruebas E2E; no implementar por prompt libre.
4. No se autoriza `apply` hasta revisión de propuesta, riesgos y ruta real de prueba. Mantener merge humano y presupuesto explícito para pruebas de inferencia.
