## Why

El Issue #490 dejó el saldo USD como valor central del reloj, aunque el requerimiento del operador era usar OpenRouter como referencia y mostrar un porcentaje. El reloj de DeepSeek debe mostrar el porcentaje proyectado a partir del saldo USD y la referencia visual acordada, manteniendo el saldo real como detalle secundario.

## What Changes

- Mostrar como valor central el porcentaje verificado por el proveedor o, si falta, el porcentaje proyectado desde un saldo USD con referencia USD 20 = 100%.
- Mantener coherentes el porcentaje central y el arco; conservar el monto observado y la naturaleza visual de la escala en el detalle secundario.
- Reemplazar en la spec activa la regla incorrecta del Issue #490 que exigía mostrar el saldo monetario en el centro.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `pwa-capacity-cards-and-reactive-state`: el valor central del reloj prioriza porcentajes verificados o proyectados y ya no usa el saldo monetario como valor principal.

## Impact

- Proyección y presentación del Dashboard y su componente analógico compartido.
- Pruebas unitarias enfocadas y Playwright para valor central, arco y layout.
- Sin cambios en APIs de proveedor, OpenCode, backend, telemetría ni política de gasto.
