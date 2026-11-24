# Proposal

## Why

Las respuestas aceptadas por la API y otras acciones durables pueden dejar un Run listo para continuar, pero el Scheduler solo descubre ese trabajo durante su sondeo periódico de 30 segundos. Ya existe un listener PostgreSQL `LISTEN/NOTIFY` para retransmitir transiciones a la API/SSE; reutilizar esa frontera para despertar al Scheduler reduce la latencia sin convertir la notificación en autoridad, cola ni sustituto de la reconciliación durable.

## What Changes

- Emitir una señal de despertar asociada a la transacción cuando una acción durable deja trabajo potencialmente elegible para el Scheduler, entregándola solo después del commit.
- Añadir al ciclo del Scheduler un listener/receptor de señales que despierte una reconciliación inmediata y consulte nuevamente PostgreSQL antes de cualquier despacho.
- Mantener los claims, fencing, fingerprint del gate, identidad del Run, permisos, idempotencia y autoridad exclusiva del Scheduler para las etapas bajo su control, incluido `DOC_CLOSING`.
- Reconciliar inmediatamente al arrancar y reconectarse, y conservar un sondeo periódico liviano como recuperación ante desconexiones, señales perdidas, duplicadas, obsoletas o agrupadas.
- Evitar bucles: las transiciones producidas por el Scheduler no deberán generar despertares que vuelvan a ejecutar el mismo trabajo; una señal sin trabajo elegible no deberá iniciar ejecución.
- Mantener la respuesta durable `ACCEPTED`, la no ejecución directa de etapas del Scheduler por la API y el stream SSE existente para la interfaz; el canal interno de despertar no sustituye el stream de UI.
- Verificar el trayecto PostgreSQL de acción aceptada a señal, reconciliación y procesamiento, incluidos duplicados, concurrencia, reconexión, pérdida de señal y estado obsoleto, con integración PostgreSQL y E2E real cuando corresponda.
- No crear una segunda cola, tabla de trabajo ni motor de workflows; no cambiar FIFO, descubrimiento de Issues, webhooks externos, despliegue productivo ni el respaldo de sondeo.

## Capabilities

### New Capabilities

<!-- No se introduce una capacidad independiente: el comportamiento extiende contratos existentes del Scheduler, despacho asíncrono y persistencia transaccional. -->

### Modified Capabilities

- `scheduler-and-recovery-convergence`: el Scheduler podrá recibir una pista de despertar y deberá reconciliar trabajo durable al arrancar, reconectarse o recibirla, sin tratarla como fuente de verdad ni producir despachos duplicados.
- `async-run-dispatch`: una acción durable aceptada podrá emitir una señal post-commit para que el Scheduler reevalúe trabajo elegible, preservando la respuesta `ACCEPTED`, la ejecución fuera de la transacción HTTP y la idempotencia.
- `postgres-durable-state`: la señal de despertar deberá vincularse a la transacción durable existente y no añadirá una cola, tabla o autoridad paralela.
- `transaction-and-concurrency-contract`: la publicación post-commit y la reconciliación despertada deberán respetar las fronteras transaccionales, claims y concurrencia existentes.

## Impact

- **Backend y Scheduler:** listener/receptor de señales, ciclo de vida de conexión, despertar y reconciliación ligera alrededor de `SchedulerService` y la autoridad de recuperación/claims existente.
- **API y persistencia:** puntos que registran respuestas/acciones durables y la publicación PostgreSQL post-commit; no se cambia el contrato de respuesta ni se despachan etapas desde la API.
- **PostgreSQL:** reutilización de `LISTEN/NOTIFY` y de las tablas/identidades actuales; se requieren pruebas de integración para commit, reconexión, duplicación, agrupación y pérdida de señales, sin nueva entidad durable.
- **UI/API SSE:** se conserva el canal SSE de transiciones para la interfaz, separado del canal interno de despertar del Scheduler.
- **Pruebas y observabilidad:** pruebas focalizadas del Scheduler, API/PostgreSQL y E2E del trayecto aceptado→señal→reconciliación→despacho, incluyendo evidencia negativa de no despacho para señales no elegibles.
