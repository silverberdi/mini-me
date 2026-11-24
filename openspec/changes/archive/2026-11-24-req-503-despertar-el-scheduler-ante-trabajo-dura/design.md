# Design

## Context

La motivación y el alcance están en `proposal.md`; los contratos observables están en las cuatro delta specs de este Change. El repositorio ya tiene una frontera PostgreSQL `LISTEN/NOTIFY` para transiciones de Run (`src/minime/services/postgres_run_event_listener.py`), un `EventBroker` en proceso para SSE y persistencia PostgreSQL de acciones, Runs, claims e intentos. Las pruebas existentes (`tests/test_postgres_run_event_listener.py` y `tests/test_run_transition_postgres_notify_e2e.py`) muestran la validación de payloads y la semántica post-commit del canal de UI.

El hueco actual es que esa señalización no participa en el ciclo del proceso Scheduler. El Scheduler debe seguir siendo la autoridad de despacho, mientras que PostgreSQL continúa siendo la autoridad del estado durable, de los claims/fencing y de la idempotencia. Por ello la notificación solo puede ser una pista efímera y no puede convertirse en una segunda cola ni en una lectura suficiente para decidir.

## Goals / Non-Goals

**Goals:**

- Reutilizar la frontera transaccional PostgreSQL existente para publicar una pista interna de despertar cuando una acción durable aceptada pueda hacer elegible trabajo del Scheduler.
- Entregar la pista únicamente al completar el commit y mantener `202 Accepted`, la identidad durable de la operación y la ejecución fuera de la transacción HTTP.
- Incorporar al ciclo Scheduler un receptor reconectable que ejecute la misma reconciliación canónica que el sondeo, al arrancar, reconectarse o recibir una pista.
- Preservar claims, fencing, autorización, fingerprint de gate, identidad de Run, intentos/dispatch intents e idempotencia; liberar transacciones antes de cualquier I/O lento.
- Mantener un sondeo periódico liviano como recuperación de señales perdidas y producir evidencia de integración PostgreSQL para commit, rollback, duplicados, agrupación, reconexión, estado obsoleto y concurrencia.
- Mantener separado el canal interno del Scheduler del listener/SSE de la interfaz y retirar solo rutas duplicadas que este Change demuestre obsoletas.

**Non-Goals:**

- Reemplazar el Scheduler por PostgreSQL LISTEN/NOTIFY, alterar FIFO o cambiar el descubrimiento de Issues.
- Ejecutar `DOC_CLOSING` u otra etapa del Scheduler desde la API, modificar la respuesta `ACCEPTED` o sustituir el stream SSE.
- Crear una cola durable, tabla de trabajo, outbox paralela, worker nuevo, motor de workflows o webhook externo.
- Cambiar la semántica de claims, permisos, gates humanos, Run identity, idempotencia o recuperación existente.
- Cambiar el intervalo/configuración de sondeo más allá de convertirlo en una reconciliación liviana de respaldo, ni incluir despliegue productivo.

## Decisions

### 1. Una señal PostgreSQL efímera y transaccional, sin nueva entidad

La API registrará la acción durable y solicitará la notificación dentro de la misma unidad de trabajo PostgreSQL ya usada por el repositorio. La publicación se hará mediante el canal PostgreSQL interno de Scheduler, con un payload pequeño y validable que identifique como mínimo proyecto, Run y causa/acción durable cuando esa identidad exista. PostgreSQL solo hace entregable un `NOTIFY` después del commit; rollback no entrega una pista utilizable.

Se conservará el canal de transición existente para SSE y se evitará enviar al `EventBroker` el evento interno. El listener de UI no se convertirá en un dispatcher del Scheduler.

Alternativas consideradas:

- **Tabla outbox/cola durable:** rechazada; duplicaría el estado durable y exigiría retención, claims y limpieza para resolver un problema que el sondeo ya puede recuperar.
- **Publicación HTTP o llamada directa API→Scheduler:** rechazada; acoplaría procesos, rompería la frontera transaccional y haría que una respuesta aceptada dependiera de la disponibilidad del Scheduler.
- **Reutilizar únicamente el canal SSE:** rechazada; mezclaría una señal interna con la interfaz y no garantiza que el proceso Scheduler reciba la pista.

### 2. Receptor reconectable dentro del ciclo existente del Scheduler

El componente Scheduler abrirá una conexión `LISTEN` dedicada y de vida acotada al proceso, con backoff de reconexión y cancelación limpia. Al completar la conexión inicial y cada reconexión, solicitará una reconciliación inmediata. Cada notificación válida solo despertará/coalescerá un ciclo; no se conservará como trabajo pendiente ni se usará para seleccionar directamente un Run.

El ciclo conservará una espera concurrente entre señal, parada y temporizador de sondeo. El sondeo seguirá invocando la misma entrada de reconciliación, por lo que startup, reconexión, pista y tick no tendrán reglas de despacho distintas. La implementación deberá impedir que una transición escrita por el propio Scheduler cause una cadena de despertares que reprocese el mismo trabajo; la coalescencia en memoria es una optimización, no una garantía de corrección.

Alternativas consideradas:

- **Cambiar LISTEN/NOTIFY por un scheduler basado en eventos:** rechazada; perdería la reconciliación periódica y convertiría una notificación no durable en autoridad.
- **Añadir un worker/cola en memoria por señal:** rechazada; introduce una segunda ruta de coordinación y no mejora la recuperación tras reinicio.
- **Duplicar la lógica de elegibilidad para el listener:** rechazada; aumentaría el riesgo de saltar gates o divergir de claims/fencing.

### 3. Reconciliación canónica antes de cualquier despacho

El receptor entregará solo un motivo de activación (`startup`, `reconnect`, `wake-up` o `poll`) a la autoridad de reconciliación existente. Esa autoridad volverá a consultar PostgreSQL y aplicará las reglas actuales de admisión, autorización, fingerprint, identidad y estado. El flujo será:

1. validar tamaño, canal y forma del payload;
2. despertar/coalescer la reconciliación;
3. seleccionar trabajo desde el estado durable actual;
4. adquirir o renovar el claim y persistir el dispatch intent en una transacción corta;
5. liberar locks/transacción;
6. invocar el workflow existente solo con la identidad y fence válidos;
7. aplicar el resultado mediante las mismas comprobaciones fenced e idempotentes.

Una pista obsoleta, duplicada, agrupada o sin trabajo elegible termina sin despacho. Dos workers compiten mediante los claims existentes; el perdedor relee el estado y no crea una invocación adicional. No se añadirá una deduplicación durable de notificaciones.

### 4. Escritura post-commit y contrato de la API

Los puntos de escritura de respuestas/acciones aceptadas reutilizarán el UoW/repositorio actual. La señal se registrará como parte de la misma transacción de base de datos, pero la respuesta HTTP se completará sin esperar al listener ni al workflow. La API no llamará al Scheduler ni a `DOC_CLOSING`; el Scheduler descubrirá la elegibilidad mediante la pista o el siguiente sondeo.

Si la operación aceptada no tiene una transición durable o una identidad que pueda producir trabajo del Scheduler, no se publicará una señal innecesaria. Si la transacción falla, el error seguirá la ruta actual y no se afirmará aceptación ni despacho. El evento SSE de actualización de UI seguirá siendo publicado por su frontera existente y no dependerá de que el listener del Scheduler esté conectado.

### 5. Sin migración de esquema; observabilidad acotada

El Change no añadirá tablas ni migraciones. Se reutilizarán tablas, eventos, claims e intentos existentes. La instrumentación registrará de forma segura el motivo de despertar, conexión/reconexión, reconciliación iniciada/omitida, resultado de claim y despacho; no incluirá secretos ni payloads arbitrarios. Los logs y evidencias distinguirán `wake-up` de `poll` para demostrar la reducción de latencia sin presentar la notificación como fuente de verdad.

El censo de retirada durante Apply deberá confirmar si existe alguna ruta de sondeo/listener o adaptador duplicado que quede sustituido. Si no hay una ruta demostrablemente obsoleta, el Removal Ledger registrará `NONE` con la búsqueda y conservará el sondeo y el listener SSE.

## Risks / Trade-offs

- **[LISTEN/NOTIFY pierde mensajes o se agrupan notificaciones]** → startup, reconexión y sondeo consultan estado durable; las notificaciones nunca son una cola.
- **[Una señal del propio Scheduler provoca un bucle]** → filtrar/coalescer motivos de activación y hacer que cada ciclo vuelva a evaluar elegibilidad/claims; probar explícitamente transiciones producidas por Scheduler.
- **[Dos workers despiertan simultáneamente]** → reutilizar la adquisición fenced y el dispatch intent idempotente existentes antes de I/O; probar dos workers contra PostgreSQL real.
- **[El listener se desconecta repetidamente]** → backoff acotado, cancelación limpia y reconciliación inmediata tras reconectar; el proceso conserva el sondeo liviano.
- **[La señal aparece antes de que el estado sea visible]** → emitir dentro de la misma transacción PostgreSQL y depender del orden post-commit; el receptor siempre relee el estado antes de despachar.
- **[El canal interno se confunde con SSE]** → mantener constantes, listener, payload y pruebas separados; verificar que la UI conserva sus eventos y que el listener SSE no invoca Scheduler.
- **[Cambiar un writer durable rompe una ruta de aceptación existente]** → localizar todos los writers y consumidores antes de Apply, conservar `202 Accepted`/idempotencia y ejecutar las pruebas PostgreSQL focalizadas y E2E después de cualquier retirada.

## Migration Plan

1. Confirmar en Apply el censo de writers de acciones durables, el listener SSE, la entrada canónica de reconciliación y los claims/dispatch intents; no modificar el estado de ramas ni crear una cola paralela.
2. Añadir el contrato de canal/payload y el registro transaccional de la pista en los writers existentes, con pruebas de commit y rollback en una base PostgreSQL desechable.
3. Conectar el listener reconectable al ciclo Scheduler y dirigir todos los motivos a la reconciliación canónica; conservar el poll y sus límites configurados.
4. Ejecutar pruebas enfocadas de backend/PostgreSQL, incluyendo duplicados, stale, reconexión, pérdida, agrupación, concurrencia, no-loop, `ACCEPTED`, no despacho API y separación SSE. Para cualquier comportamiento UI observable, el ejecutor configurado correrá la prueba Playwright declarada pertinente con Chromium real; no se delegará esa ejecución al operador.
5. Repetir las pruebas después de retirar cualquier ruta demostrablemente obsoleta. Registrar SHA candidato, comandos, códigos de salida y efectos observables como evidencia del Change.

Rollback consiste en detener la suscripción de wake-up y volver a usar la reconciliación por poll con el código anterior; no requiere revertir datos ni migración. Si una señal no es observable, el Scheduler debe continuar seguro por reconciliación periódica. No se incluye reinicio del Scheduler ni despliegue productivo en este Change.

## Open Questions

No quedan preguntas diferibles que cambien las specs, la arquitectura o las tareas. Los nombres finales de módulos/canales y el punto exacto de integración deberán seguir los contratos y convenciones que el inventario de Apply confirme, sin alterar las decisiones anteriores.
