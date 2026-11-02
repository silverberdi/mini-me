# Tasks: F11 — Supervisión móvil proactiva y notificaciones Web Push

## 1. Persistencia y Criptografía VAPID
- [x] 1.1 Crear modelo SQLAlchemy `PushSubscription` en `src/minime/db/models.py` y repositorio en `src/minime/db/repository.py` con campos para endpoint, p256dh, auth, device_label, categorías y estado activo.
- [x] 1.2 Crear migración Alembic para la tabla `push_subscriptions` y verificar invariantes físicas de esquema.
- [x] 1.3 Implementar generador y lector seguro de claves VAPID en `src/minime/services/web_push_service.py` con persistencia en directorio protegido o lectura desde variables de entorno.

## 2. Servicio de Despacho Web Push
- [x] 2.1 Implementar `WebPushService` en `src/minime/services/web_push_service.py` con firma VAPID, cifrado RFC 8291, entrega asíncrona y captura de fallos sin interrumpir la orquestación.
- [x] 2.2 Implementar desactivación automática (`is_active = False`) al recibir respuestas HTTP 404 o 410 (Gone) de los gateways de notificación.
- [x] 2.3 Conectar los eventos duraderos del orquestador (`HUMAN_REQUIRED`, transiciones de etapa elegibles y `COMPLETED`/`FAILED`) con el despacho de notificaciones hacia las suscripciones activas del operador.

## 3. Endpoints REST de la API
- [x] 3.1 Implementar `GET /api/v1/push/vapid-public-key` en `src/minime/api/app.py` para exponer la clave pública base64url al operador autenticado.
- [x] 3.2 Implementar `POST /api/v1/push/subscriptions` y `DELETE /api/v1/push/subscriptions` para alta, actualización y revocación idempotente.
- [x] 3.3 Implementar `POST /api/v1/push/test` para emitir una notificación de prueba directa a la instalación del operador.

## 4. Frontend Angular y Service Worker
- [x] 4.1 Configurar listener de eventos `push` y `notificationclick` en el Service Worker de la PWA para mostrar la notificación nativa y abrir la URL contextual (`/trabajo-actual?run=...`).
- [x] 4.2 Implementar `PushNotificationService` en `frontend/src/app/core/push-notification.service.ts` para gestionar permisos del navegador, suscribirse mediante `pushManager` y comunicarse con el backend.
- [x] 4.3 Integrar componente modal/popover de configuración Web Push en la interfaz (navbar de `AppComponent`), con indicador de estado, toggle de activación, selector de categorías y botón de prueba.
- [x] 4.4 Compilar bundle de producción de Angular (`npm run build`) y sincronizar con `src/minime/static/`.

## 5. Pruebas Automatizadas y Evidencia
- [x] 5.1 Escribir pruebas unitarias y de integración para `WebPushService`, serialización VAPID, modelo de suscripciones y endpoints REST de la API.
- [x] 5.2 Escribir pruebas para el manejo de `notificationclick` y contratos PWA offline.
- [x] 5.3 Registrar evidencia determinista de pruebas aprobadas y validación de endpoints.

## 6. Recuperación de revisión independiente desde la UI
- [x] 6.1 Exponer en el modelo de `Trabajo Actual` el estado durable del intento de `CODE_REVIEW` y mostrar la acción únicamente para un Run activo recuperable con candidato e intento identificables.
- [x] 6.2 Integrar la acción autenticada con los endpoints existentes de autorización y reanudación, encadenando sus identificadores y conservando `target_run_id`.
- [x] 6.3 Añadir pruebas backend/frontend para autorización obsoleta o repetida, doble clic, error de red y ausencia de veredicto; verificar que no se crea un Run paralelo.
- [ ] 6.4 Ejecutar E2E real sobre el Run existente: autorización durable, reanudación del mismo Run y nueva invocación del revisor independiente configurado en PostgreSQL contra el candidato exacto.
- [ ] 6.5 Repetir el code review independiente después del nuevo SHA; registrar el resultado estructurado, sus findings y evidencia de fail-closed si vuelve a ser inválido.
- [ ] 6.6 Validar manualmente en la PWA móvil el estado del botón, mensajes de éxito/error y refresco del Run contra el SHA desplegado en preview; invalidar la validación si cambia el SHA.
