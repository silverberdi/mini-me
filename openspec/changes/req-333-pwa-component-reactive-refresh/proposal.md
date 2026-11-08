# Change: PWA Component-Reactive Refresh and Blind Global Polling Retirement (Ref #333)

## Why
El temporizador global periódico de 10 segundos en `RefreshService` ejecuta peticiones indiscriminadas en segundo plano que recargan señales y sobreescriben colecciones completas, interrumpiendo formularios, menús desplegables y modales de configuración (especialmente en *Proyectos* y *Admin Modelos*). En una arquitectura Angular basada en componentes, cada vista debe gobernar su estrategia de actualización: las pantallas de configuración deben permanecer estables y bajo demanda, la supervisión en vivo debe ser puramente reactiva a eventos del servidor (SSE), y la resolución de atención humana debe ofrecer respuesta optimista inmediata en vez de depender de un reloj global ciego.

## What Changes
- **REMOVAL**: Se elimina el temporizador global periódico ciego (`setInterval` de 10 segundos) de `RefreshService`.
- **MODIFICATION**: `RefreshService` se transforma en un proveedor reactivo impulsado por Server-Sent Events (`/api/v1/events`), eliminando la sobreescritura masiva de señales en segundo plano.
- **NEW CAPABILITY / STABILITY**: Las pantallas de configuración y administración (`ProyectosComponent`, `AdminModelsComponent`) cargan datos exclusivamente en `ngOnInit` o tras mutaciones explícitas del usuario (crear, editar, activar/desactivar), garantizando que formularios, campos de texto y menús desplegables jamás se reinicien mientras el usuario interactúa.
- **NEW CAPABILITY / OPTIMISTIC UI**: Al enviar una respuesta o aclaración para una compuerta `HUMAN_REQUIRED`, el modal y el banner de atención humana se ocultan de inmediato en la UI (actualización optimista) y muestran estado de procesamiento sin esperar la confirmación diferida del backend.
- **MODIFICATION**: Vistas de supervisión (`TrabajoActualComponent`, `TrabajoComponent`, `BacklogComponent`) actualizan su estado exclusivamente ante eventos SSE de ciclo de vida (`run.transition`, `request.created`, `quota.update`), reflejando cambios en tiempo real.
- **MODIFICATION**: Las series pesadas y métricas históricas de costo en `DashboardComponent` utilizan almacenamiento en memoria amortiguado (5 a 10 minutos) con recarga manual bajo demanda, evitando saturación de red y recálculos continuos.

## Capabilities

### Modified Capabilities
- `pwa-capacity-cards-and-reactive-state`: Se elimina el requisito de polling periódico global como mecanismo primario de refresco; la reactividad pasa a ser gobernada por eventos del servidor (SSE), ciclo de vida por componente y actualizaciones optimistas para interacción humana.

## Impact
- **Frontend**:
  - `frontend/src/app/core/refresh.service.ts`: Eliminación de `timer`, `setupTimer` e `interval`, desacoplamiento de recargas masivas.
  - `frontend/src/app/features/proyectos/proyectos.component.ts`: Carga aislada en `ngOnInit`, estabilidad de modales y formularios de configuración de modelos.
  - `frontend/src/app/features/admin-models/admin-models.component.ts`: Carga aislada bajo demanda.
  - `frontend/src/app/features/trabajo-actual/trabajo-actual.component.ts`: Actualización optimista inmediata ante respuesta de operador en gates.
  - `frontend/src/app/features/dashboard/dashboard.component.ts`: Caché y recarga amortiguada de gráficas de costos.
- **Backend / APIs**: Sin cambios de contratos de API ni de esquema de base de datos.
