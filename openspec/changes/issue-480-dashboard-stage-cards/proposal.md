## Why

El progreso por etapas de la tarjeta Change activo no conserva la presentación que el operador reconoce en Trabajo Actual: muestra una secuencia de números sin los paneles ni las etiquetas de etapa. Alinear ambas vistas evita que el mismo avance se interprete de forma distinta.

## What Changes

- Mostrar las diez etapas del Dashboard con la jerarquía visual de Trabajo Actual: panel por etapa, número circular y etiqueta.
- Reutilizar el orden, los nombres y las clases de estado compartidos, manteniendo el diseño adaptable y compacto del Dashboard.
- Verificar en navegador los estados y tamaños de pantalla, incluida la carga real de la ilustración de la etapa.

## Capabilities

### New Capabilities

### Modified Capabilities
- `execution-operations-dashboard`: el indicador de progreso por etapas del Change activo adopta las tarjetas y estados visibles de Trabajo Actual.

## Impact

- Frontend Angular: tarjeta Change activo del Dashboard y presentación compartida de etapas.
- E2E Playwright del Dashboard; sin cambios de API, persistencia, Backlog ni comportamiento de Trabajo Actual.
