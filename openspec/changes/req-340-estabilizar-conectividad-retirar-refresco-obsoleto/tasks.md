## 1. Estabilización de conectividad en RefreshService

- [x] 1.1 Modificar el manejador `onerror` de SSE en `RefreshService` para no conmutar `isConnected` a falso ante desconexiones transitorias si el navegador está en línea (`navigator.onLine`).
- [x] 1.2 Ajustar la revalidación y lecturas secundarias en `read()` para que fallos parciales o reconexiones en segundo plano no activen el estado desconectado de forma espuria.
- [x] 1.3 Crear pruebas unitarias en `frontend/tests/` verificando la estabilidad de `isConnected` durante reconexiones SSE y comprobando que solo conmuta a falso ante desconexión real de red.

## 2. Retiro de controles de refresco redundantes en AppComponent

- [x] 2.1 Eliminar el botón manual de refresco `🔄` y el texto de sincronización (`Sincronizando…`) en `frontend/src/app/app.component.ts`.
- [x] 2.2 Limpiar propiedades o enlaces de estado del encabezado relacionados con el refresco manual superfluo.
- [x] 2.3 Actualizar las pruebas unitarias y E2E del shell para confirmar la ausencia del botón obsoleto y la preservación del estado de conectividad limpio.

## 3. Retiro de «Test Connection» en AdminModelsComponent y backend

- [x] 3.1 Eliminar la columna «Conexión» y el botón `Test Connection` de la plantilla en `frontend/src/app/features/admin-models/admin-models.component.ts`.
- [x] 3.2 Retirar propiedades, estados y métodos asociados (`testConnection`, `testingProviders`, `connectionDiagnostics`, `connectionErrors`) en `AdminModelsComponent`.
- [x] 3.3 Revisar el backend (`src/minime/`) para retirar o simplificar de forma segura el endpoint de prueba de conexión sin sondas artificiales a proveedores.
- [x] 3.4 Actualizar las pruebas unitarias de administración de modelos en frontend y backend.

## 4. Verificación integral y pruebas E2E

- [x] 4.1 Ejecutar suite unitaria de frontend (`npm --prefix frontend test`) con 0 errores.
- [x] 4.2 Ejecutar build de frontend (`npm --prefix frontend run build`) con 0 advertencias o errores.
- [x] 4.3 Ejecutar suite de pruebas de backend (`pytest`).
- [x] 4.4 Ejecutar pruebas Playwright E2E para comprobar la estabilidad visual sin parpadeos de desconexión y la eliminación efectiva de controles obsoletos.
