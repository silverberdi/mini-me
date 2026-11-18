# Capability: web-push-notification-delivery

## Purpose
Proveer un servicio backend de despacho y firma VAPID de notificaciones Web Push sobre transiciones de estado duraderas, compuertas humanas y resultados finales, con persistencia PostgreSQL, deduplicación y tolerancia a fallos.

## ADDED Requirements

### Requirement: VAPID Public Key Distribution
El sistema SHALL exponer la clave pública VAPID en un endpoint seguro accesible para operadores autenticados.

#### Scenario: Operador autenticado obtiene la clave VAPID
- **Given** un operador autenticado mediante sesión o token válido
- **When** realiza una solicitud `GET /api/v1/push/vapid-public-key`
- **Then** el backend responde `200 OK` con un objeto `{ "public_key": "..." }` en formato base64url
- **And** la respuesta no expone ninguna clave privada ni secreto interno.

#### Scenario: Solicitud anónima rechazada
- **Given** una solicitud sin credenciales de operador
- **When** invoca `GET /api/v1/push/vapid-public-key`
- **Then** el backend responde `401 Unauthorized`.

---

### Requirement: Push Subscription Persistence and Lifecycle
El sistema SHALL registrar y mantener las suscripciones Web Push por dispositivo e instalación asociadas al operador.

#### Scenario: Registro o actualización idempotente de suscripción
- **Given** una suscripción Web Push válida con `endpoint`, `keys.p256dh` y `keys.auth`
- **When** el operador envía `POST /api/v1/push/subscriptions` con el payload de suscripción
- **Then** el backend persiste o actualiza la suscripción en PostgreSQL y responde `201 Created`
- **And** la suscripción queda marcada como activa con sus categorías por defecto habilitadas.

#### Scenario: Revocación explícita de suscripción
- **Given** una suscripción registrada previamente
- **When** el operador envía `DELETE /api/v1/push/subscriptions?endpoint=...`
- **Then** el backend marca la suscripción como inactiva (`is_active = False`) y responde `200 OK`
- **And** no se envían más notificaciones a dicho endpoint.

---

### Requirement: Durable Notification Dispatch on Stage Transition and Human Gate
El sistema SHALL emitir notificaciones Web Push únicamente ante transiciones verificables de la orquestación.

#### Scenario: Emisión en bloqueo de atención humana (HUMAN_REQUIRED)
- **Given** un Run que transiciona de forma duradera a `HUMAN_REQUIRED`
- **When** se procesa la transición en el orquestador
- **Then** el servicio Web Push despacha una notificación a todas las suscripciones activas del operador suscritas a `category_human_required`
- **And** el payload incluye título "mini me: Atención Requerida", detalle del Run y URL contextual hacia `/trabajo-actual`.

#### Scenario: Fallo del gateway remoto no corrompe la ejecución
- **Given** un endpoint de suscripción que devuelve HTTP 410 (Gone) o HTTP 500
- **When** el servicio Web Push intenta enviar la notificación
- **Then** el servicio captura el error, desactiva la suscripción inválida si es 410, y registra el diagnóstico
- **And** la transición y ejecución del Run continúan normalmente sin interrupciones.
