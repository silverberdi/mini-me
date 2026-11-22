## Why

El Dashboard dedica dos tarjetas extensas a listas de Runs y solicitudes que ya se consultan en Trabajo y Backlog. El operador necesita identificar de inmediato el Change activo y su etapa, en especial desde móvil, sin abrir otra vista ni esperar una compuerta humana.

## What Changes

- Sustituir las tarjetas actuales de Runs recientes y Solicitudes de Cambio por una tarjeta compacta y adaptable para el Change activo del proyecto seleccionado.
- Mostrar nombre del Change, número y título del Request asociado cuando estén disponibles, etapa y estado actuales, e ilustración oficial de la etapa.
- Usar los Runs ya cargados por `RefreshService`; enlazar a Trabajo Actual para supervisar la ejecución.
- Mostrar un estado de reposo claro cuando no haya ejecución activa, con acceso a Trabajo o Backlog.
- No representar un porcentaje de avance si la fuente actual no ofrece una medida verificable.

## Capabilities

### New Capabilities

<!-- Ninguna: el Dashboard ya tiene una capacidad especificada para observabilidad de Changes y Runs. -->

### Modified Capabilities

- `execution-operations-dashboard`: concretar la presentación compacta del Change activo en el Dashboard y su estado vacío.

## Impact

- Frontend Angular: componente del Dashboard y sus pruebas de UI/E2E.
- Datos: `RefreshService.runs()` y los Requests del proyecto seleccionado; sin cambios de API, base de datos ni estado de orquestación salvo que el Apply demuestre una carencia real en los datos existentes.
- Vistas Trabajo, Trabajo Actual y Backlog conservan su comportamiento.
