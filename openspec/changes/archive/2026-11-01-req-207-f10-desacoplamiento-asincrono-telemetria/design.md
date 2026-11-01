# Design

## Context

El backend ya concentra la API FastAPI, coordinación, adaptadores de proveedores, persistencia PostgreSQL y read models del dashboard. El frontend Angular ya usa `RefreshService` y Signals, pero conserva el componente visual radial y varias decisiones derivadas por vista. El diseño debe integrarse con `LifecycleTransitionAuthority`, las reglas de transacción/concurrencia, la recuperación durable y las specs existentes de capacidad y observabilidad; no crea una API paralela, una cola de tickets ni una segunda fuente de verdad.

## Goals / Non-Goals

**Goals:**

- Responder rápido con una aceptación durable y continuar el trabajo mediante una unidad de ejecución desacoplada, reanudable y observable.
- Reutilizar los adaptadores existentes y encapsular cada fuente de cuota detrás de una estrategia pequeña, con parseo fail-closed y caché TTL de 60 segundos.
- Producir un snapshot operativo único para la PWA y proyectarlo con Signals en todas las vistas afectadas.
- Preservar identidad de Run/candidato, gates humanos, historial, auditoría, límites de gasto y aislamiento de sesiones.
- Retirar el gauge radial y las proyecciones duplicadas solo después de paridad y E2E real; registrar el inventario y la evidencia en el ledger del Change.

**Non-Goals:**

- No desplegar, administrar producción, cambiar el proveedor de tickets ni implementar ADO.
- No crear microservicios, una cola durable paralela, un scheduler nuevo, una saga adicional o una base de datos de cuotas duplicada.
- No autoautorizar preguntas humanas, saltarse gates canónicos, consumir inferencia como heartbeat ni convertir una lectura de readiness en capacidad disponible.
- No cambiar el contrato global de OpenSpec ni adelantar capacidades de fases no autorizadas.

## Decisions

### 1. Aceptación durable y worker con sesión fresca

El endpoint valida permisos, conflicto de admisión e idempotency key dentro de una transacción corta, registra o recupera el Run y devuelve `202` con identidad y estado. El worker vuelve a leer el Run, reclama mediante la autoridad de ciclo de vida, abre sesiones acotadas por transición y nunca conserva la sesión HTTP durante I/O de proveedor. Se elige esta composición sobre `BackgroundTasks` sin persistencia o una cola nueva porque aprovecha el checkpoint/recuperación existente y evita perder trabajo en reinicios.

### 2. Estrategias de observación, no proveedores hardcodeados en la UI

El servicio de telemetría recibe un registro de estrategias/adaptadores por proveedor. Antigravity usa su comando `/usage`, Codex su fuente de capacidad de solo lectura y DeepSeek su balance autenticado; cada estrategia devuelve un DTO normalizado con fuente, cuenta, timestamp, ventana, reset, valor y estado de parsing. Se rechaza parsear la salida en componentes o inventar un promedio común porque rompería DIP y permitiría presentar datos no verificables.

### 3. Caché efímera y persistencia de evidencia existente

La caché de observación es memoria acotada por proveedor/cuenta con TTL máximo de 60 segundos; no se añade una tabla que replique la fuente externa. Las transiciones de salud, capacidad o eventos que ya exige el contrato vigente siguen usando PostgreSQL y la unidad de trabajo existente. Una observación vieja o malformada se etiqueta como tal y nunca autoriza dispatch.

### 4. Read model único para la PWA

El backend expone un snapshot que ya contiene runs, Requests, elegibilidad, cuotas y timestamps. `RefreshService` conserva Signals de fuente y Signals computadas para las vistas; Dashboard, Trabajo y Trabajo actual consumen esa misma fuente. Se elige esto sobre llamadas independientes por componente porque elimina carreras y la duplicación activa/siguiente. El refresco manual invalida y vuelve a obtener el snapshot completo.

### 5. Recuperación mediante claims y transiciones existentes

El arranque busca únicamente Runs no terminales con lease/heartbeat vencido, obtiene un claim fenced y reconcilia el checkpoint antes de admitir trabajo nuevo. La continuación automática usa solo transiciones ya autorizadas y evidencia durable; `HUMAN_REQUIRED`, capacidad desconocida y contradicciones permanecen bloqueantes. Se reutiliza el recovery authority actual en vez de añadir un daemon paralelo.

### 6. Retiro seguro y compatibilidad

Se censarán writers/callers de endpoints síncronos, gauges, cálculos de cuota estáticos y selecciones locales duplicadas. Tras pruebas verdes del sustituto, se retiran esas rutas y se repiten pruebas unitarias, integración, E2E de backend y navegador. Se preservan migraciones aplicadas, eventos, historial, Runs/Jobs/attempts y artefactos OpenSpec; cualquier elemento aún alcanzable se marca `RETAIN-WITH-REASON` y bloquea la declaración de cierre completo.

## Risks / Trade-offs

- **[Worker perdido entre aceptación y ejecución]** → persistir la intención antes de responder, reclamar por lease/claim y reconciliar huérfanos al arrancar.
- **[Dos instancias despachan el mismo Run]** → claim fenced/lock transaccional, idempotencia y evidencia del propietario antes de I/O externo.
- **[CLI cambia el formato `/usage`]** → parser versionado y fail-closed; conservar la última observación marcada stale sin presentarla como real.
- **[TTL provoca lecturas externas concurrentes]** → coalescer consultas por clave de proveedor y aplicar límites de concurrencia/cooldown existentes.
- **[Snapshot parcial o UI stale]** → versionar/timestampar el snapshot, indicar frescura y no confirmar sincronización si falla una revalidación.
- **[Auto-recovery salta un gate humano]** → matriz explícita de transiciones permitidas y prueba negativa para `HUMAN_REQUIRED`/contradicciones.
- **[Retiro rompe consumidores históricos]** → inventario estático/dinámico, pruebas post-retiro y conservación de datos/migraciones; no borrar rutas sin evidencia de sustitución.

## Migration Plan

1. Implementar el contrato de aceptación y observación detrás de la autoridad existente, con compatibilidad de lectura para el read model actual.
2. Activar el worker/recovery y validar idempotencia, aislamiento, reinicio, transiciones y fuentes reales con E2E.
3. Migrar los consumidores de la PWA al snapshot/Signals y validar desktop, móvil, teclado, light/dark y WCAG AA.
4. Retirar gauge, cálculos y dispatch síncronos demostrados obsoletos; repetir la suite completa y documentar el ledger.
5. Rollback: deshabilitar la nueva admisión/worker mediante configuración segura y conservar Runs aceptados para reconciliación; no reabrir estados terminales ni borrar evidencia. El despliegue lo ejecuta el CI/CD del proyecto.

## Open Questions

Ninguna pregunta abierta que cambie las specs o el enfoque. Los detalles de comandos/formatos concretos deben resolverse durante el inventario y pruebas contra las versiones instaladas, con resultado desconocido fail-closed si la fuente no es compatible.

### 7. Stream de eventos Server-Sent Events (SSE) para latencia cero

En lugar de depender exclusivamente de polling cada 10 segundos para percibir cambios de stage, intervenciones humanas o actualización de cuotas, el backend expone `GET /api/v1/events` con `text/event-stream`. Un `EventBroker` en memoria distribuye eventos atómicos a las conexiones activas. En el frontend, `RefreshService` se suscribe mediante `EventSource` nativo, actualizando Signals inmediatamente al recibir eventos y preservando polling diferido como mecanismo de respaldo ante caídas de red.
