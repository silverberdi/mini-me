## 1. Scheduler transition publication

- [x] 1.1 Trace the canonical Run stage persistence path and add a PostgreSQL `NOTIFY` for actual stage transitions in the same transaction as the authoritative Run update.
- [x] 1.2 Keep the notification payload bounded to project ID, Run ID, and transition fields; prove rollback and non-transition Run writes emit no notification.

## 2. API and PWA event delivery

- [x] 2.1 Add an API-lifespan-owned PostgreSQL listener using the existing psycopg dependency; validate notifications, reconnect safely, and close the listener on shutdown.
- [x] 2.2 Forward valid scheduler notifications through the existing `EventBroker` as `run.transition`; after PostgreSQL listener recovery, publish `run.resync` to still-connected SSE clients.
- [x] 2.3 On each SSE open/reconnect and on `run.resync`, refresh only the selected project's authoritative Run projection and mark it current only after the API read succeeds.
- [x] 2.4 When a subscriber queue cannot accept a Run transition, make only that subscriber reconnect so it re-reads the authoritative snapshot; preserve other streams and add no periodic polling.

## 3. Real PostgreSQL integration evidence

- [x] 3.1 Add a PostgreSQL integration/E2E test that performs a real scheduler stage transition through an independent database connection, observes the API listener and authenticated SSE event, and verifies the subsequent Run API projection contains the persisted stage.
- [ ] 3.2 **Diferida hasta desplegar este candidato.** Entonces, añadir/ejecutar browser E2E que pruebe que una reconexión SSE, la recuperación del listener API y una transición Run perdida detectada por el servidor refrescan la proyección autoritativa, mientras los demás suscriptores siguen conectados y no hay recarga de página ni polling global periódico.
- [x] 3.3 Verify no event is broadcast for a rolled-back transition, malformed/oversized notifications are rejected safely, and existing API-originated SSE events still work.
- [ ] 3.4 **Diferida hasta desplegar este candidato.** Sobre el SHA desplegado, ejecutar las pruebas focalizadas y la validación requerida del proyecto contra PostgreSQL; registrar invocación, resultado y efectos observables sobre el estado autoritativo.
