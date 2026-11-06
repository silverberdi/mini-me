## Why

La PWA registra Angular Service Worker y precarga el shell, pero no informa cuando una versión nueva queda lista. El operador puede seguir usando una interfaz obsoleta después de un despliegue y no ver controles ya publicados.

## What Changes

- La PWA detecta y presenta de forma visible una actualización del shell cuando el service worker confirma que la nueva versión está lista.
- El aviso ofrece recargar para activar la versión nueva; no interrumpe una sesión mediante una recarga inesperada.
- Se mantiene el alcance frontend-only y la caché actual limitada al shell público.

## Capabilities

### New Capabilities

### Modified Capabilities
- `pwa-responsive-and-offline-pwa`: definir el comportamiento observable del aviso de actualización disponible en la PWA.

## Impact

- `frontend/src/app/app.component.ts` y el servicio Angular `SwUpdate`.
- Pruebas frontend y build Angular.
- Sin cambios a API, backend, configuración de despliegue, manifiesto ni política de caché.
