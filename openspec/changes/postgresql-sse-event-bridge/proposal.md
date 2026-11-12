## Why

Issue #366 pide que las transiciones de Run producidas por `minime-scheduler` lleguen en tiempo real a los clientes SSE servidos por `minime-api`, y que la interfaz recupere el estado autoritativo al restablecer la conexión o cuando el servidor detecte que perdió una transición. Hoy el endpoint SSE distribuye mediante un broker en memoria del proceso API, por lo que no existe un canal entre ambos servicios; además, una cola SSE llena descarta eventos en silencio y una reconexión no vuelve a consultar la proyección.

## What Changes

- Publicar una notificación PostgreSQL `NOTIFY` al confirmar una transición operativa de Run producida por el scheduler.
- Escuchar esas notificaciones desde `minime-api` y retransmitirlas por el endpoint autenticado `/api/v1/events` existente.
- Hacer que el consumidor actual de SSE refresque la proyección autoritativa del Run cuando recibe la transición, sin confiar en el payload como estado ni iniciar sondeos periódicos.
- Al restablecerse SSE, reconciliar los Runs del proyecto seleccionado con la API antes de marcar las observaciones como actuales.
- Si el listener PostgreSQL del API se recupera después de una interrupción, emitir una señal SSE de resincronización para que los clientes aún conectados relean su proyección autoritativa.
- Cuando una cola SSE no admita una transición de Run, hacer visible la pérdida y forzar la reconexión solo del suscriptor afectado para que la lectura autoritativa lo reconcilie.
- Mantener el payload limitado a la identidad y datos mínimos de la transición; no transportar secretos ni duplicar el estado persistido.

## Capabilities

### New Capabilities

Ninguna.

### Modified Capabilities

- `pwa-capacity-cards-and-reactive-state`: precisar que las transiciones originadas en el proceso scheduler alcanzan el cliente a través del puente PostgreSQL → API → SSE y actualizan la proyección existente sin polling global.

## Impact

- Componentes existentes: persistencia de transiciones del scheduler, servicio de eventos PostgreSQL, endpoint SSE autenticado y `RefreshService` Angular.
- Prueba de integración con PostgreSQL que ejercite la transición real, el listener API y un cliente SSE autenticado; verificar también recuperación tras reconexión y saturación de un suscriptor.
- No agrega una API, broker externo, tabla de eventos, cola de tickets, polling periódico ni responsabilidad de despliegue productivo.
