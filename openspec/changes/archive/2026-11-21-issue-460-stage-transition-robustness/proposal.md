## Why

En una ejecución real, las transiciones de propuesta, Apply, Verify y cierre documental pueden tratar correcciones legítimas como drift, despachar dos veces el mismo workflow o avanzar con un SHA anterior. Además, los gates no siempre explican qué evidencia cambió ni qué efecto tiene cada opción; el Issue #460 reúne estas fallas del mismo ciclo operativo y pide corregirlas sin debilitar las validaciones.

## What Changes

- Rebasar la evidencia de hashes de tareas y escenarios en la misma transacción que persiste la aprobación de la revisión independiente, conservando las comprobaciones de factibilidad y drift real.
- Tras Apply y sus correcciones, ejecutar las pruebas pertinentes y fijar el candidato en un commit antes de Verify; Verify y las etapas posteriores deben identificar ese mismo SHA inmutable.
- Hacer que la API registre idempotentemente la respuesta al gate y deje el Run elegible; el Scheduler será la única autoridad que despache DOC_CLOSING, usando el claim de etapa existente para impedir ejecuciones concurrentes. La PWA confirmará de inmediato la aceptación y mostrará la etapa pendiente sin afirmar que el agente ya se despachó.
- Indicar en el prompt nativo de Propose que cada Requirement de una delta spec debe incluir al menos un escenario; la validación estricta de OpenSpec sigue siendo la autoridad.
- Enriquecer el payload de gates con los requisitos/tareas afectados, un diff legible y opciones que describan la acción y su consecuencia, sin inventar evidencia ni cambiar las autorizaciones humanas. `diff`, `affected_items` y `option_explanations` serán opcionales para mantener compatibilidad con gates existentes.

## Capabilities

### New Capabilities

Ninguna.

### Modified Capabilities

- `openspec-native-propose`: conservar la coherencia de la evaluación de complejidad tras una corrección de propuesta aprobada e incluir la instrucción de escenarios por Requirement.
- `openspec-native-apply-and-verify`: fijar y verificar el SHA candidato después de pruebas exitosas y antes de despachar Verify.
- `openspec-orchestration-continuity`: centralizar el despacho de DOC_CLOSING bajo el Scheduler y mejorar la evidencia y explicación de los gates.

## Impact

Afecta la coordinación de revisiones de propuesta, Apply/Verify y DOC_CLOSING en `orchestration_coordinator.py`, la ruta de respuesta a gates en `api/app.py`, la señal de estado en `trabajo-actual.component.ts`, el prompt nativo de Propose y las proyecciones existentes de gates. Debe reutilizar el claim durable de etapa, los registros de acciones y el estado JSONB actuales; approval y hashes se guardan atómicamente y no se anticipa una migración ni un nuevo servicio. No cambia los workflows OpenSpec, las reglas fail-closed, el contrato de revisión independiente, las autorizaciones humanas, el merge ni el despliegue.
