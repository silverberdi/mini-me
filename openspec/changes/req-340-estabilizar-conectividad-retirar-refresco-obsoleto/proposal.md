## Why

La experiencia de usuario en la aplicación web sufre actualmente de dos remanentes técnicos del ciclo anterior:
1. La indicación de conectividad en `RefreshService` conmuta abruptamente a «Sin conexión» cada vez que el canal SSE (`/api/v1/events`) realiza su ciclo normal de reconexión periódica o cuando una lectura secundaria falla de forma transitoria, generando un parpadeo molesto y falsas alarmas transversales con el banner rojo de desconexión.
2. Persisten controles manuales heredados que ya no tienen razón de ser bajo la arquitectura reactiva actual: el botón manual de refresco `🔄` y el texto «Sincronizando…» en el encabezado general (`AppComponent`), así como la columna y botón «Test Connection» en `AdminModelsComponent` que intenta sondas activas contra proveedores de IA, arriesgando consumo de saldo/cuotas y contradiciendo el Contrato Rector 2.0.

Es necesario resolver esto ahora para estabilizar la percepción de conectividad del operador, limpiar el shell de la aplicación y retirar código muerto y sondas artificiales innecesarias.

## What Changes

- **Estabilización de conectividad en `RefreshService`**: El estado `isConnected` y el banner de desconexión se gobernarán estrictamente por la presencia de red del navegador (`navigator.onLine`) y por fallos fatales confirmados del backend en peticiones HTTP principales, sin alternar a desconectado durante reintentos normales de conexión SSE (`onerror` con reconexión programada) ni por fallos de endpoints secundarios.
- **Retiro de botón manual de refresco y texto de sincronización en `AppComponent`**: Se eliminan del encabezado el botón manual `🔄` y la etiqueta `Sincronizando…`. Las actualizaciones continúan ocurriendo de forma reactiva a través de eventos SSE y mutaciones del usuario.
- **Retiro de «Test Connection» en `AdminModelsComponent`**: Se elimina la columna «Conexión» y el botón `Test Connection` en la tabla de modelos. El catálogo se rige de forma fidedigna por las credenciales y capacidades reales instaladas y observadas (`auth.json`, variables de entorno, harnesses configurados), sin sondas artificiales que consuman cuotas o dependan de estado volátil.
- **Limpieza de código y pruebas asociadas**: Se retiran del frontend y backend los controladores, métodos y estados accesorios dedicados exclusivamente a invocar o renderizar diagnósticos de prueba activa de conexión por modelo.

## Capabilities

### New Capabilities
<!-- None -->

### Modified Capabilities
- `pwa-app-shell-and-queue`: Se actualiza la especificación del shell para eliminar el requisito de controles de refresco manual/intervalo periódico en la barra superior y establecer que la indicación de conectividad no oscile ante reconexiones transitorias de eventos SSE en segundo plano.
- `provider-model-administration-ui`: Se elimina el requisito de control «Test Connection» por proveedor/modelo en la vista de administración de modelos, consolidando la visualización del catálogo en función de las observaciones y configuraciones reales instaladas.

## Impact

- Frontend: Modificaciones en `RefreshService`, `AppComponent` y `AdminModelsComponent`. Eliminación de elementos de interfaz obsoletos (botón refresco, etiqueta sincronización, botón y estados de test connection).
- Backend: Deprecación/retiro seguro de endpoints de prueba de conexión de proveedores que no tengan consumidores válidos.
- Pruebas: Actualización de pruebas unitarias y E2E para reflejar la eliminación de los controles obsoletos y asegurar la estabilidad del estado de conexión.
