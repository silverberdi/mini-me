# Tasks

## 1. Decisiones y contratos de seguridad

- [ ] 1.1 Resolver con el propietario el modelo mínimo de alcance de conexiones: (A) conexión vinculada a proyecto con credencial cifrada y caché separada —recomendado— o (B) conexión global reutilizable con vínculos explícitos; verificar que la opción queda registrada como decisión vigente antes de crear la migración.
- [ ] 1.2 Resolver con el propietario el mecanismo de inyección de runtime: (A) socket local de retransmisión con ACL y vida limitada —recomendado cuando la CLI lo soporte— o (B) argumentos de configuración con prueba de que no exponen secretos en argv, `/proc`, logs ni evidencia; verificar compatibilidad real con Codex y Antigravity antes de implementarlo.
- [ ] 1.3 Definir los contratos mínimos de transporte, autenticación, diagnóstico sanitizado, catálogo y perfil efímero MCP; verificar con pruebas de contrato que ningún DTO de API o evento contenga credenciales.

## 2. Persistencia PostgreSQL y secretos

- [ ] 2.1 Añadir modelos SQLAlchemy para conexiones MCP y caché de herramientas/recursos conforme a la decisión 1.1, con constraints de estado, unicidad, timestamps y diagnóstico no secreto; verificar metadata y repositorios con pruebas focalizadas `pytest tests/test_mcp_connections.py`.
- [ ] 2.2 Añadir migración Alembic reversible y mínima, incorporar las nuevas invariantes al preflight PostgreSQL y comprobar aislamiento de base candidata; verificar con `pytest tests/test_mcp_migration.py` contra PostgreSQL desechable y una prueba de rollback.
- [ ] 2.3 Implementar cifrado/descifrado de credenciales mediante la clave maestra de runtime sin fallback implícito; verificar persistencia cifrada, fallo cerrado sin clave y ausencia de secretos en respuestas/logs con `pytest tests/test_mcp_secrets.py`.
- [ ] 2.4 Implementar purga transaccional de tokens, credenciales y caché en revocación/eliminación; verificar idempotencia y que no quedan consumidores MCP activos con `pytest tests/test_mcp_revocation.py`.

## 3. Adaptadores MCP y API FastAPI

- [ ] 3.1 Implementar adaptadores mínimos para HTTP/SSE y stdio que realicen saludo inicial, `tools/list`, recursos aplicables, health y traducción de errores; verificar handshake y descubrimiento con un servidor MCP de prueba real en `pytest tests/test_mcp_protocol_integration.py`.
- [ ] 3.2 Implementar autenticación OAuth2 con estado de un solo uso ligado a la sesión, callback validado, almacenamiento seguro del refresh token y renovación atómica; verificar autorización exitosa, estado inválido, revocación y renovación con `pytest tests/test_mcp_oauth.py` usando un proveedor OAuth2 controlado.
- [ ] 3.3 Implementar registro/validación de API Key y Bearer token, incluyendo endpoint, transporte, saludo y estado ACTIVA solo tras conectividad autenticada; verificar éxito, credencial inválida y endpoint caído con `pytest tests/test_mcp_token_auth.py`.
- [ ] 3.4 Añadir endpoints autenticados para catálogo, alta, inicio/callback OAuth2, validación, health, renovación, descubrimiento y revocación; verificar autorización de operador, payloads sanitizados y estados observables con `pytest tests/test_mcp_api.py`.
- [ ] 3.5 Publicar eventos/diagnósticos sanitizados y notificaciones de operador usando los mecanismos existentes, sin crear una cola durable MCP; verificar que rollback no publica éxito y que la repetición de una operación ya aplicada es idempotente con `pytest tests/test_mcp_events.py`.

## 4. Runtime de agentes

- [ ] 4.1 Implementar el puerto de resolución de perfil MCP y el adaptador concreto elegido en 1.2, ligado al proyecto, Run y agente autorizado; verificar que una conexión no autorizada, revocada o no ACTIVA no produce perfil con credenciales mediante `pytest tests/test_mcp_runtime_profile.py`.
- [ ] 4.2 Integrar renovación previa, entrega efímera y fail-closed en la preparación real del Run sin modificar la política de proveedores ni abrir navegador; verificar invocación de una herramienta MCP desde el runtime real con `pytest tests/test_mcp_runtime_integration.py` y evidencia de llamada, resultado y efecto.
- [ ] 4.3 Retirar dentro del alcance cualquier ruta/adaptador/control MCP duplicado o consumidor que contradiga el nuevo puerto; verificar con `rg -n -i "mcp|stitch" src frontend/src` y pruebas focalizadas que solo queda una autoridad de conexión.

## 5. Centro de Control Angular

- [ ] 5.1 Añadir la ruta `/conexiones-mcp`, el componente y modelos/servicio API para catálogo, estados, capacidades y acciones, separado de Administración; verificar compilación y pruebas unitarias focalizadas con `npm --prefix frontend run test -- tests/mcp-connections.test.mjs`.
- [ ] 5.2 Implementar formularios y estados observables para OAuth2, API Key/Bearer, error, renovación, revocación y herramientas descubiertas sin almacenar secretos en estado persistente o service worker; verificar sanitización y comportamiento con `npm --prefix frontend run test -- tests/mcp-connections.test.mjs`.
- [ ] 5.3 Implementar navegación real de la barra lateral y deep link autenticado; el ejecutor configurado SHALL verificarlo en navegador real con `npm --prefix frontend run test:e2e -- tests/e2e/mcp-connections.spec.ts`, incluyendo viewport desktop/tablet pertinente y resultado observable.

## 6. Verificación integrada y cierre del Change

- [ ] 6.1 Ejecutar el recorrido E2E OAuth2 completo con un proveedor MCP controlado y PostgreSQL candidato, conservando evidencia de consentimiento, callback, refresh token cifrado, handshake, `tools/list` y estado ACTIVA; verificar `pytest tests/test_mcp_e2e.py` y artefactos sanitizados.
- [ ] 6.2 Ejecutar el recorrido E2E de API Key/Bearer, invocar una herramienta desde el runtime real y conservar evidencia de invocación, respuesta y efecto; verificar `pytest tests/test_mcp_runtime_e2e.py` contra el servidor MCP controlado.
- [ ] 6.3 Ejecutar escenarios deterministas de credencial inválida, refresh revocado, endpoint caído y herramienta ausente; verificar fail-closed, diagnóstico/notificación y ausencia de éxito ficticio con `pytest tests/test_mcp_failure_e2e.py`.
- [ ] 6.4 Ejecutar el navegador y build focalizados en frontend —`npm --prefix frontend run test:e2e -- tests/e2e/mcp-connections.spec.ts` y `npm --prefix frontend run build`— y conservar resultados contra el SHA candidato; no reutilizar evidencia visual o E2E de otros Changes.
- [ ] 6.5 Ejecutar validación estricta del Change con `openspec validate req-537-gestion-de-conexiones-e-integraciones-mc --strict` y revisar que cada requisito tiene escenarios, cada tarea tiene señal verificable y no se modificó código fuera del alcance.
