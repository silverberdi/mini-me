## Why

El Issue #407 identifica tres fricciones dentro del mismo ciclo de trabajo: la factibilidad puede rechazar una ruta de ejecución ya evidenciada, un error corregible del informe puede abrir un gate de inmediato y el cierre documental o la respuesta por CLI pueden detener una reanudación que ya tiene una vía canónica. Resolverlas reduce intervenciones humanas innecesarias sin debilitar las comprobaciones de evidencia, la autoridad humana ni los workflows oficiales de OpenSpec.

## What Changes

- Alinear la comprobación de la capacidad del actor `execution` con la evidencia verificable del workflow nativo `workflow:execution:apply`, sin exigir además una referencia redundante `profile:execution` en cada tarea.
- Asegurar que el gate de factibilidad siempre ofrezca una opción seleccionable que despache OpenSpec Update nativo para el mismo Change. Los bloqueos por evidencia real o ausente seguirán sin poder omitirse con texto libre.
- Añadir hasta dos reintentos correctivos de la evaluación de factibilidad cuando el informe tenga errores estructurales o de mapeo verificables. Cada reintento recibirá los diagnósticos concretos; falta de capacidad, evidencia desconocida, fallo de CLI o error de ejecución seguirán el camino existente fail-closed.
- En DOC_CLOSING, después de confirmar el resultado satisfactorio de Sync, usar el comando nativo de OpenSpec Archive en modo no interactivo y basar el resultado en su código de salida y artefactos observables. No detener el cierre por comparar párrafos semánticamente cuando la CLI nativa ya puede resolver la operación; un fallo real de CLI conserva el Change y se reporta.
- Añadir `minime request run <project_id> --response <texto>` para responder al gate vigente mediante la misma autoridad, persistencia auditable e idempotencia que usa la interfaz web. La respuesta no autoriza por sí sola una acción que el gate no permita.

## Capabilities

### New Capabilities

Ninguna. El Change modifica comportamientos existentes del ciclo OpenSpec y del control de acciones del operador.

### Modified Capabilities

- `openspec-native-propose`: evidencia de capacidad del actor, opciones del gate de factibilidad y reintentos correctivos acotados antes de escalar errores de forma humana.
- `two-phase-pr-and-closure`: cierre documental determinista mediante la CLI nativa después de Sync verificado, sin una comparación semántica paralela.
- `operator-actions-control-plane`: respuesta al gate vigente desde CLI con las mismas precondiciones, auditoría e idempotencia del control existente.

## Impact

Cambios de comportamiento previstos en `ProposalFeasibilityEvaluator` y el flujo de evaluación de Propose, el dispatch existente de OpenSpec Update y Archive, la skill instalada de archivo si el inventario confirma que contiene la comparación que detiene el caso, y `minime request run` junto con su integración con acciones durables. Las pruebas deben cubrir positivos y negativos de las tres fricciones y el recorrido CLI contra el control durable existente. No se agregan proveedores, motores de evaluación, tablas, estados de ciclo de vida ni una implementación propia de OpenSpec. El Change no incluye despliegue productivo ni declara pruebas E2E reales sin evidencia.
