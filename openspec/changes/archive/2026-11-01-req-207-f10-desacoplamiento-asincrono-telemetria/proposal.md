# Proposal

## Why

Las ejecuciones y aclaraciones humanas todavía pueden mantener una petición HTTP abierta durante inferencias largas, exponiendo al operador a timeouts del proxy aunque el Run continúe. Además, la PWA mezcla proyecciones de estado, presenta cuotas con una visualización poco densa y necesita una lectura verificable de las ventanas reales de capacidad para que sus decisiones operativas no se basen en valores estáticos o duplicados.

## What Changes

- Convertir el despacho de Runs y las operaciones de gates incluidas en el alcance en comandos aceptados de forma inmediata (`202 Accepted`), con ejecución en segundo plano, sesiones transaccionales aisladas, idempotencia y recuperación durable tras reinicio.
- Consolidar la observación de capacidad mediante estrategias/adaptadores de proveedor: lectura real de Antigravity y Codex, balance vivo de DeepSeek, parseo de ventana rodante de cinco horas y reset timestamp, caché acotada de 60 segundos y estados explícitos cuando la fuente no sea verificable.
- Sustituir los velocímetros semicirculares de cuota por tarjetas compactas y accesibles con barra horizontal, porcentaje o saldo real, proveedor/modelo, estado operativo y cuenta regresiva de reset.
- Unificar las proyecciones reactivas de `activeRun`, `nextEligible` y estados derivados en Dashboard, Trabajo y Trabajo actual mediante Signals, evitando que un Run activo aparezca como siguiente trabajo o se duplique entre vistas.
- Conectar el refresco manual del encabezado con una revalidación completa, indicador transitorio y estado de sincronización observable.
- Corregir contraste, foco, estados y semántica del modo claro para cumplir WCAG AA en las superficies afectadas sin ocultar estados desconocidos.
- Auto-recuperar Runs huérfanos al arrancar, continuar automáticamente las transiciones estándar de implementación a pruebas y revisión cuando exista evidencia suficiente, y bloquear/ocultar acciones engañosas para Requests posteriores mientras haya un Run activo.
- Retirar las rutas visuales y de coordinación sustituidas cuando la nueva autoridad alcance paridad E2E, conservando historial, migraciones, auditoría y evidencia durable.

## Capabilities

### New Capabilities

- `async-run-dispatch`: aceptación HTTP inmediata y ejecución desacoplada de Runs, gates y aclaraciones con continuidad y aislamiento transaccional.
- `quota-window-telemetry`: observación verificable de cuotas/balances por proveedor con estrategias, ventanas de cinco horas y caché controlada.
- `pwa-capacity-cards-and-reactive-state`: tarjetas de capacidad, sincronización transversal, refresco integral y accesibilidad visual de la PWA.
- `run-autorecovery-and-autonomous-continuation`: detección de Runs huérfanos y continuación segura de etapas estándar sin confirmaciones artificiales.

### Modified Capabilities

No se modifica el contrato existente de una capacidad: los cinco contratos nuevos de esta propuesta añaden la superficie F10 y deben integrarse con las autoridades ya existentes sin duplicarlas.

## Impact

- **Backend:** rutas FastAPI de ejecución/gates, coordinador de orquestación, workers en segundo plano, unidad de trabajo PostgreSQL, persistencia de Runs/Jobs/eventos y recuperación de arranque.
- **Proveedores:** adaptadores CLI/API y parser de observaciones de capacidad; no se enviarán turnos de inferencia para leer cuotas cuando exista una fuente de solo lectura.
- **Frontend:** `RefreshService`, modelos/read model y componentes Angular de Dashboard, Trabajo, Trabajo actual, navegación y tarjetas de cuota; se retirará el componente radial sustituido.
- **Pruebas y operación:** contratos HTTP `202`, pruebas de concurrencia/reinicio, E2E reales de invocación y efectos, pruebas de navegador responsive/accesibilidad y ledger de retiro. El despliegue productivo permanece fuera del Change y pertenece al CI/CD del proyecto.
