# Capability: pwa-mobile-push-subscription

## Purpose
Permitir a los operadores suscribir sus dispositivos móviles (iPhone y Android) a notificaciones Web Push desde la PWA Angular, gestionar permisos, seleccionar categorías de alerta y acceder directamente al contexto operativo al pulsar la notificación.

## ADDED Requirements

### Requirement: Browser Permission and Push Subscription Management
La PWA gestionará el ciclo de vida de los permisos y la suscripción local ante el Service Worker y el backend.

#### Scenario: Activación exitosa de notificaciones en móvil
- **Given** un navegador compatible con soporte de Service Worker y Push API (e.g. Safari iOS 16.4+ o Chrome Android)
- **When** el operador pulsa "Activar Notificaciones" en el panel de configuración
- **Then** el navegador solicita el permiso al usuario mediante el diálogo estándar
- **And** si es concedido (`granted`), la PWA obtiene la clave VAPID, genera la suscripción con `pushManager.subscribe` y la registra en el backend.

#### Scenario: Manejo de permiso denegado
- **Given** un navegador donde el operador denegó el permiso (`denied`)
- **When** la PWA inspecciona el estado de notificaciones
- **Then** muestra claramente un aviso explicativo indicando que los permisos deben habilitarse en los ajustes del sistema o del navegador
- **And** el botón de activación permanece deshabilitado sin lanzar excepciones no controladas.

---

### Requirement: Direct Contextual Navigation on Notification Click
Al pulsar una notificación Web Push recibida en el sistema operativo, la PWA debe abrir la vista relevante.

#### Scenario: Apertura de Run bloqueado en HUMAN_REQUIRED
- **Given** una notificación push recibida con URL `/trabajo-actual?run=R-123&project=PROJ`
- **When** el operador pulsa la notificación en su dispositivo
- **Then** el Service Worker enfoca la ventana existente de la PWA o abre una nueva ventana navegando a `/trabajo-actual?run=R-123&project=PROJ`
- **And** el operador accede directamente al formulario de respuesta para desbloquear el Run.

---

### Requirement: Test Notification Dispatch
El operador dispondrá de una acción explícita para comprobar la recepción real en su dispositivo.

#### Scenario: Envío de notificación de prueba dirigida
- **Given** un dispositivo con suscripción activa
- **When** el operador pulsa "Enviar Notificación de Prueba"
- **Then** el backend emite inmediatamente una notificación dirigida a dicha instalación
- **And** la PWA o el sistema operativo del móvil muestra el banner de notificación confirmando la conectividad de extremo a extremo.
