# Tasks

## 1. Censo y contratos de integración

- [x] 1.1 Inventariar los writers de acciones durables, la unidad de trabajo PostgreSQL, `src/minime/services/postgres_run_event_listener.py`, la entrada canónica de reconciliación del Scheduler y los claims/dispatch intents; verificar mediante una nota de implementación y referencias de código que cada consumidor se reutiliza, modifica o conserva dentro de este Change
- [x] 1.2 Definir el canal interno de despertar y su payload mínimo validable, separado del canal de transiciones SSE; verificar con pruebas de validación de tamaño, canal, forma e identidad que un payload inválido no inicia reconciliación

## 2. Publicación transaccional de la pista

- [x] 2.1 Integrar la publicación de la pista en los writers existentes de acciones aceptadas dentro de la misma transacción PostgreSQL, sin tablas, filas outbox, migraciones ni llamadas directas al Scheduler; verificar con una prueba PostgreSQL de commit que la notificación queda entregable después del commit y que la respuesta conserva `202 Accepted` e identidad durable
- [x] 2.2 Cubrir rollback y acciones que no pueden volver elegible trabajo del Scheduler; verificar con una prueba PostgreSQL que no se entrega una pista utilizable, no se ejecuta una etapa Scheduler-owned y se conserva la ruta de error existente
- [x] 2.3 Mantener la autoridad de la API y la interfaz; verificar con `tests/test_human_gate_current_payload_postgres_e2e.py` y las pruebas SSE focalizadas que `DOC_CLOSING` no se despacha desde la API y que los eventos de UI siguen funcionando independientemente del listener interno

## 3. Receptor y ciclo de reconciliación del Scheduler

- [x] 3.1 Añadir al ciclo del Scheduler un listener `LISTEN` dedicado, cancelable y reconectable con backoff acotado, sin convertir la notificación en cola o fuente de verdad; verificar con pruebas focalizadas de lifecycle que la conexión se cierra limpiamente y que una reconexión no deja tareas pendientes en memoria
- [x] 3.2 Dirigir `startup`, `reconnect`, `wake-up` y `poll` a la misma entrada canónica de reconciliación, manteniendo el sondeo periódico liviano; verificar con pruebas del Scheduler que arranque y reconexión reconcilian inmediatamente y que el siguiente poll recupera una señal perdida
- [x] 3.3 Validar, coalescer y descartar señales duplicadas, obsoletas o agrupadas antes de reconciliar sin seleccionar directamente un Run; verificar con pruebas que una señal vacía u obsoleta produce cero despachos y nunca salta gates
- [x] 3.4 Evitar bucles causados por transiciones producidas por el propio Scheduler; verificar con una prueba focalizada que procesar una transición Scheduler-owned no genera despachos repetidos ni una cadena de despertares sin trabajo elegible

## 4. Claims, idempotencia y límites transaccionales

- [x] 4.1 Reutilizar la consulta durable de elegibilidad, autorización, fingerprint del gate, identidad del Run, claims/fencing e idempotent dispatch intent existentes; verificar con pruebas de reconciliación que una pista solo despacha trabajo aún elegible y que el estado obsoleto no altera la evidencia autoritativa
- [x] 4.2 Mantener las transacciones de claim e intent acotadas antes de la ejecución externa; verificar con una prueba que no queda lock ni transacción de notificación abierta mientras corre el workflow lento
- [x] 4.3 Verificar la convergencia de dos pistas iguales y dos workers concurrentes sobre PostgreSQL real; usar `tests/test_stage_invocation_lifecycle_postgres_e2e.py` como cobertura existente y añadir la prueba focalizada del despertar, comprobando como máximo un despacho válido y estado observable del perdedor

## 5. Retirada segura y evidencia de integración

- [x] 5.1 Retirar únicamente una ruta de listener, sondeo o adaptador demostrablemente duplicada por esta integración y repetir las pruebas afectadas; si no existe código obsoleto demostrable, registrar `NONE` con la búsqueda realizada y conservar el sondeo y el listener SSE
- [x] 5.2 Añadir `tests/test_scheduler_wakeup_postgres_e2e.py` con evidencia E2E PostgreSQL del trayecto acción aceptada → commit → pista → despertar → reconciliación → despacho, incluyendo commit, rollback, duplicado, agrupación, stale, reconexión, pérdida, concurrencia y no-loop; verificar ejecutando solo `python -m pytest tests/test_scheduler_wakeup_postgres_e2e.py` y capturando código de salida, SHA y efectos observables
- [x] 5.3 Ejecutar la regresión backend acotada de las fronteras modificadas, incluyendo `tests/test_postgres_run_event_listener.py`, `tests/test_run_transition_postgres_notify_e2e.py` y `tests/test_human_gate_current_payload_postgres_e2e.py`; verificar que todas terminan con código de salida 0 sin afirmar despliegue, reinicio del Scheduler ni pruebas simuladas como E2E
