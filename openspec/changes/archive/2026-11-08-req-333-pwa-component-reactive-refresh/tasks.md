# Tasks: PWA Component-Reactive Refresh and Blind Global Polling Retirement (Ref #333)

## 1. Desmantelamiento del Polling Global Ciego en RefreshService

- [x] 1.1 Eliminar el temporizador periódico `setInterval`, `timer`, `setupTimer` y la señal `interval` de `RefreshService`
- [x] 1.2 Preservar `connectEvents()` (SSE `/api/v1/events`) como el canal de reactividad en tiempo real impulsado por el backend
- [x] 1.3 Mantener la invocación `read()` exclusivamente para la inicialización al arrancar la app y la acción manual «Refrescar»

## 2. Aislamiento y Estabilidad en Vistas de Configuración

- [x] 2.1 Confinar la carga de datos en `ProyectosComponent` a `ngOnInit` y a la confirmación exitosa de creación o edición
- [x] 2.2 Asegurar que los modales de edición y formularios de modelos preserven sus valores, foco y selecciones sin reseteos
- [x] 2.3 Garantizar que `AdminModelsComponent` opere estrictamente bajo demanda sin sufrir interferencia de eventos ajenos

## 3. Actualización Optimista de Compuertas de Atención Humana

- [x] 3.1 Implementar el ocultamiento optimista inmediato del modal/banner de `HUMAN_REQUIRED` en `TrabajoActualComponent` al enviar la respuesta
- [x] 3.2 Mostrar indicador visual inline de *"Procesando respuesta..."* durante el vuelo de la petición HTTP
- [x] 3.3 Implementar reversión fail-safe de la compuerta visible y notificación de error si el endpoint `/api/v1/orchestration/runs/{id}/gate` falla

## 4. Reactividad por Eventos SSE y Caché Amortiguada en Dashboard

- [x] 4.1 Conectar los componentes `TrabajoActualComponent`, `TrabajoComponent` y `BacklogComponent` a las señales reactivas emitidas por eventos SSE
- [x] 4.2 Implementar caché en memoria de 5 minutos para las series analíticas de `/api/v1/dashboard/overview` en `DashboardComponent`
- [x] 4.3 Permitir invalidación inmediata de la caché de costos cuando el operador acciona el botón manual «Refrescar»

## 5. Pruebas Unitarias y E2E de Frontend

- [x] 5.1 Crear prueba unitaria en `frontend/tests/pwa-reactive-components.test.mjs` certificando la ausencia de `setInterval` en `RefreshService` y la estabilidad de formularios
- [x] 5.2 Crear prueba E2E en `frontend/e2e/pwa-reactive-interaction.spec.ts` verificando que un formulario de edición no se resetee con el tiempo y que el gate responda optimísticamente
- [x] 5.3 Ejecutar la suite completa de pruebas de frontend (`npm --prefix frontend test`) comprobando 100% de éxito
