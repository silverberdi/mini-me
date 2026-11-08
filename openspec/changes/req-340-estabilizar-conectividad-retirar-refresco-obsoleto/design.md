## Context

La aplicación web mini me opera como una PWA con navegación por cinco vistas principales y comunicación en tiempo real vía Server-Sent Events (`/api/v1/events`) gestionada por `RefreshService`. Actualmente:
- La reconexión estándar de SSE dispara `onerror` de forma recurrente durante el ciclo de vida normal del navegador/servidor, provocando que `isConnected` pase a falso y active transitoriamente el banner de desconexión sin que haya una pérdida real de conectividad.
- El encabezado de la aplicación conserva un botón manual de refresco con icono de giro (`🔄`) y un texto de sincronización (`Sincronizando…`) concebidos en una fase previa de polling manual.
- La pantalla de administración de modelos (`AdminModelsComponent`) incluye una columna de prueba activa de conexión (`testConnection`) que realiza invocaciones HTTP a `/api/v1/admin/providers/{provider}/test`, lo que contradice el principio de no ejecutar sondas artificiales que consuman cuotas o dependan de estado volátil (Contrato Rector 2.0).

## Goals / Non-Goals

**Goals:**
- Estabilizar `RefreshService.isConnected`: reflejar el estado real de red del navegador (`navigator.onLine`) y la alcanzabilidad comprobada de la API central, evitando oscilaciones durante reconexiones de fondo de SSE o fallos transitorios en peticiones secundarias.
- Simplificar el shell (`AppComponent`): retirar el botón manual `🔄` y la etiqueta `Sincronizando…` manteniendo la reactividad por eventos SSE y navegación contextual.
- Limpiar `AdminModelsComponent`: retirar la columna y control de «Test Connection», así como el estado interno y métodos asociados a diagnósticos de prueba activa por modelo.
- Retirar código muerto en frontend y endpoints de backend que queden huérfanos sin consumidores válidos.

**Non-Goals:**
- No alterar los flujos de SSE existentes para eventos de ciclo de vida de ejecuciones (`run.transition`, etc.).
- No alterar la autenticación, configuración de roles de proyecto ni la administración de harnesses observados.
- No modificar el sistema de notificaciones push móviles.

## Decisions

### 1. Desacoplar la reconexión SSE del indicador de desconexión transversal
- **Decisión**: El callback `onerror` del stream SSE (`EventSource`) no conmutará `isConnected` a falso de forma inmediata cuando el navegador esté en línea (`navigator.onLine === true`). El navegador reconecta automáticamente los flujos SSE. Solo si una petición HTTP crítica al backend falla con error de red (status 0, timeout o rechazo de conexión) o si `navigator.onLine` es falso, se marcará `isConnected = false`.
- **Alternativas consideradas**:
  - *Mantener `onerror` con debounce/temporizador*: Innecesariamente complejo; introduce estados intermedios y no previene falsos positivos si el stream tarda unos segundos en reenganchar.
  - *Eliminar SSE por completo*: Descartado; la reactividad ante eventos de ejecución (`run.transition`, etc.) es necesaria y funciona adecuadamente.

### 2. Retiro de controles manuales de refresco en `AppComponent`
- **Decisión**: Eliminar el botón manual de refresco `🔄` y la etiqueta `Sincronizando…` de la cabecera. La carga inicial y la sincronización reactiva por eventos y cambios de proyecto son suficientes.
- **Alternativas consideradas**:
  - *Ocultar el botón solo en móvil*: No resuelve la redundancia conceptual en escritorio.

### 3. Retiro de pruebas artificiales de conexión en `AdminModelsComponent`
- **Decisión**: Eliminar la columna «Conexión» y el botón `Test Connection` en la tabla de modelos. Retirar los métodos y propiedades `testConnection`, `diagnosticStatusLabel`, `testingProviders`, `connectionDiagnostics` y `connectionErrors`. Retirar o marcar como obsoleto el endpoint de prueba en backend si no tiene otros consumidores.
- **Alternativas consideradas**:
  - *Reemplazar el botón con un ping pasivo*: Innecesario; la presencia de credenciales configuradas en `auth.json` / variables de entorno ya determina la disponibilidad real de los modelos.

## Risks / Trade-offs

- **[Riesgo] El backend se detiene mientras el navegador sigue en línea** → **Mitigación**: Cuando el usuario navega o realiza cualquier acción que dispare una petición HTTP central (`/api/v1/projects`, etc.), el fallo de red detectado conmuta `isConnected` a falso y despliega el banner de advertencia inmediatamente.
- **[Riesgo] Pérdida de eventos durante la reconexión SSE** → **Mitigación**: `RefreshService` realiza un refresco reactivo al restablecer la conexión (`onopen`) para asegurar que el estado en memoria sea coherente.
