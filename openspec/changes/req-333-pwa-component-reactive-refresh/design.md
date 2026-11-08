# Technical Design: PWA Component-Reactive Refresh and Blind Global Polling Retirement (Ref #333)

## Context
Ver `proposal.md` y `specs/pwa-capacity-cards-and-reactive-state/spec.md`.
Actualmente `RefreshService` inicializa un temporizador periódico ciego (`setInterval` cada 10 segundos) que invoca `read()`, re-consultando 5 endpoints REST y sobreescribiendo señales globales (`projects`, `runs`, `requests`, `quotas`, `cost`). El backend ya dispone de un canal Server-Sent Events (`/api/v1/events`) que emite eventos de ciclo de vida (`run.transition`, `request.created`, `project.pause_changed`, `quota.update`). El polling global interfiere con los formularios de edición de modelos y proyectos en Angular, cerrando diálogos o restableciendo selecciones del operador.

## Goals / Non-Goals

**Goals:**
- Desmantelar completamente el temporizador periódico `setInterval` de `RefreshService`.
- Confinar el ciclo de vida de datos en vistas de configuración (`ProyectosComponent`, `AdminModelsComponent`) a `ngOnInit` y post-mutación explícita.
- Implementar actualización optimista instantánea al resolver compuertas `HUMAN_REQUIRED` en `TrabajoActualComponent`.
- Apoyar la reactividad de `TrabajoActualComponent`, `TrabajoComponent` y `BacklogComponent` exclusivamente en eventos SSE entrantes.
- Introducir caché amortiguada (mínimo 5 minutos) para series y métricas pesadas de costo en `DashboardComponent`.

**Non-Goals:**
- No alterar contratos REST existentes ni endpoints de la API FastAPI.
- No introducir WebSockets redundantes cuando SSE ya satisface la unidireccionalidad servidor → cliente.
- No modificar el esquema de base de datos ni migraciones Alembic.

## Decisions

### Decisión 1: Retirar `setupTimer` y la señal `interval` de `RefreshService`
- **Elección**: Eliminar el temporizador periódico global de raíz. `RefreshService.start()` se limita a suscribir el canal SSE (`connectEvents()`) y ejecutar una carga inicial única (`read()`).
- **Alternativa descartada**: Pausar condicionalmente el temporizador según la ruta activa. Se descartó porque mantiene un polling global innecesario y propenso a fugas de temporizadores en componentes desacoplados.

### Decisión 2: Ciclo de vida On-Demand en pantallas de configuración
- **Elección**: `ProyectosComponent` y `AdminModelsComponent` gestionan sus propios estados locales de edición (`editProject`, `newProject`, perfiles de modelos). Las recargas de proyectos o modelos se invocan únicamente al montar el componente o tras un `submit` exitoso.
- **Alternativa descartada**: Depender de la señal global `refresh.projects()` para popular formularios reactivos mientras el usuario está escribiendo.

### Decisión 3: Actualización optimista de compuertas de atención humana
- **Elección**: En `TrabajoActualComponent`, al ejecutar `submitHumanAction()`, el componente limpia inmediatamente la señal local del gate activo y proyecta un estado inline de *"Procesando respuesta..."*. Si la llamada API falla, restaura el gate y muestra el error.
- **Alternativa descartada**: Esperar pasivamente a que el ciclo de actualización de red reciba el cambio del backend (causando 2 a 5 segundos de latencia visual donde el gate parece congelado).

### Decisión 4: Caché amortiguada para series analíticas en Dashboard
- **Elección**: La consulta a `/api/v1/dashboard/overview` se condiciona a un umbral de validez de 5 minutos (`CACHE_TTL_MS = 300_000`). Si la última lectura tiene menos de 5 minutos, se reutiliza la observación retenida a menos que el operador pulse "Refrescar" explícitamente.
- **Alternativa descartada**: Consultar `/api/v1/dashboard/overview` en cada evento SSE menor.

## Risks / Trade-offs

- **[Riesgo] Pérdida de eventos si la conexión SSE se interrumpe**  
  → *Mitigación*: `EventSource` cuenta con reconexión automática nativa del navegador. Además, al reconectarse o al presionar el botón visible "Refrescar" en la cabecera, se revalida el estado completo. La cabecera conserva la indicación explícita "Sin conexión / Conectado".
- **[Riesgo] Discrepancia temporal en actualización optimista si el backend rechaza la respuesta humana**  
  → *Mitigación*: Si el POST a `/api/v1/orchestration/runs/{id}/gate` retorna un error HTTP (ej. 400 o 500), el componente captura la excepción, revierte la compuerta visible y notifica el error de inmediato al operador.
