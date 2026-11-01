# Proposal: F11 — Supervisión móvil proactiva y notificaciones Web Push

## Why

El operador de mini me supervisa ciclos autónomos de desarrollo desde dispositivos móviles (iPhone y tablets Android). Actualmente, para enterarse de que un Run avanzó de fase, terminó o requiere una intervención humana crítica (`HUMAN_REQUIRED`), el operador debe mantener la PWA abierta en primer plano o consultar manualmente. Esto genera retrasos en la respuesta operativa y reduce la agilidad del ciclo de entrega. Es necesario que mini me emita notificaciones Web Push reales, seguras y contextuales cuando ocurran transiciones de estado duraderas, sin exigir la apertura continua del navegador.

## What Changes

- **Backend Web Push y VAPID:**
  - Exponer la clave pública VAPID en `/api/v1/push/vapid-public-key` para que el navegador configure su suscripción.
  - Gestionar suscripciones por dispositivo/instalación en `/api/v1/push/subscriptions` (alta idempotente, consulta, actualización de categorías y revocación).
  - Enviar notificaciones de prueba dirigidas a la instalación en `/api/v1/push/test`.
  - Integrar un servicio de despacho Web Push (`WebPushService`) desacoplado de la ejecución principal, basado en eventos durables (transiciones de etapa, bloqueo `HUMAN_REQUIRED` y finalización `COMPLETED`/`FAILED`).
- **Persistencia PostgreSQL:**
  - Migración Alembic para la tabla `push_subscriptions` vinculada a la sesión y operador autenticado, almacenando endpoint, claves criptográficas (`p256dh`, `auth`), metadatos de instalación y preferencias de categorías.
- **Frontend Angular PWA:**
  - Implementar `PushNotificationService` en Angular para gestionar permisos del navegador, suscribirse mediante el Service Worker y almacenar el estado local.
  - Panel de control de notificaciones integrado en las vistas existentes (sin crear una sexta vista principal paralela), permitiendo activar/desactivar push, configurar categorías y probar la recepción.
  - Integración con el Service Worker para manejar el evento `push` y `notificationclick`, redirigiendo directamente a `/trabajo-actual?run={run_id}&project={project_id}`.
- **Seguridad y Resiliencia:**
  - Aislamiento estricto entre operadores: una notificación solo se envía a las suscripciones del operador autorizado.
  - Deduplicación y tolerancia a fallos: errores en el envío push nunca bloquean ni corrompen el avance del orquestador.
  - Cero secretos expuestos en payloads o respuestas públicas.

## Capabilities

### New Capabilities
- `web-push-notification-delivery`: servicio backend de despacho y firma VAPID de notificaciones Web Push sobre transiciones durables, compuertas humanas y resultados finales con deduplicación y aislamiento de fallos.
- `pwa-mobile-push-subscription`: gestión de ciclo de vida de suscripciones Web Push, permisos del navegador, preferencias por instalación y apertura contextual en el Service Worker de la PWA Angular.

### Modified Capabilities
Ninguna existente: se extiende la superficie de observabilidad y entrega de F10 sin modificar la autoridad de orquestación, intake ni contratos preexistentes.

## Impact

- **Backend:** nuevos endpoints en `src/minime/api/app.py`, servicio `src/minime/services/web_push_service.py`, tabla y modelo SQLAlchemy/Alembic en `src/minime/db/`.
- **Frontend:** servicio Angular `PushNotificationService`, controles de configuración en el shell y manejo de `push` en Service Worker.
- **Operación:** supervisión desatendida en móviles sin mantener la pantalla encendida ni polling continuo.
