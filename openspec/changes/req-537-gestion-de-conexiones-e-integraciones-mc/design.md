# Design

## Context

La API FastAPI es monolítica modular y el frontend Angular ya concentra la navegación en `app.routes.ts` y `app.component.ts`. La persistencia usa SQLAlchemy/Alembic sobre PostgreSQL; existe almacenamiento protegido para credenciales de GitHub, pero no un contrato MCP ni un catálogo de conexiones. La motivación y el comportamiento requerido están en `proposal.md` y `specs/mcp-connections-and-integrations/spec.md`.

## Goals / Non-Goals

**Goals:**

- Añadir un único límite de dominio MCP reutilizable por UI, API y runtime, con adaptadores pequeños para transportes y métodos de autenticación.
- Mantener el secreto fuera del cliente, Git, repositorios destino, logs y evidencia; hacer las operaciones idempotentes y transaccionales respecto al estado PostgreSQL.
- Reutilizar la autenticación/autorización de operador, la unidad de trabajo PostgreSQL, el broker de eventos y los contratos de invocación existentes.
- Hacer observable el handshake, descubrimiento, renovación, inyección y fallo, con diagnósticos sanitizados y correlación con el Run.

**Non-Goals:**

- No construir un marketplace, un framework de plugins general, una segunda API, un scheduler nuevo ni soporte ADO.
- No desplegar servidores MCP, administrar infraestructura productiva ni trasladar credenciales al repositorio administrado.
- No inventar una implementación específica de Stitch: Stitch será un caso de prueba OAuth2 del adaptador genérico.
- No guardar un historial completo de mensajes MCP; solo el estado actual, catálogo vigente y evidencia operativa mínima necesaria.

## Decisions

### 1. Contrato MCP con adaptadores de transporte y autenticación

Definir un contrato interno pequeño para `connect/handshake/discover/health/revoke` y separar transporte HTTP/SSE de stdio y autenticación OAuth2 de API Key/Bearer. El servicio de aplicación coordina el caso de uso y los adaptadores traducen protocolos y errores a diagnósticos sanitizados.

Se elige composición e interfaces mínimas sobre una clase por proveedor: permite agregar Stitch, GitHub, Figma o servicios internos sin hardcodear nombres en el núcleo. No se reutiliza `ProviderConnectionDiagnostic` como modelo MCP porque ese contrato está orientado a proveedores de modelos y no expresa handshake, tools/resources ni revocación.

### 2. PostgreSQL como autoridad y cifrado de credenciales

Añadir modelos SQLAlchemy para una conexión MCP y su caché de herramientas/recursos, con relación al proyecto cuando aplique, estado acotado, timestamps, diagnóstico no secreto y unicidad suficiente para evitar duplicados. El material secreto se cifra antes de persistir usando una clave maestra de runtime ya suministrada por configuración segura; no se reutiliza el almacén de archivos de GitHub porque el Issue exige vinculación a PostgreSQL.

La migración Alembic será reversible, incluirá índices/constraints mínimos y no migrará secretos existentes. La eliminación purgará primero el material cifrado y luego el catálogo, dentro de una operación transaccional. El preflight PostgreSQL deberá incluir las tablas/columnas nuevas en sus invariantes sin auto-reparación.

### 3. OAuth2 interactivo separado del consumo desasistido

El endpoint de inicio crea un estado de autorización de un solo uso y redirige al proveedor; el callback valida estado, código, redirect y respuesta antes de cifrar refresh/access tokens. El frontend solo inicia el flujo y muestra estados; nunca recibe ni almacena tokens. La renovación ocurre en backend justo antes de health o preparación de Run y actualiza el registro de forma atómica.

Se prefiere OAuth2 estándar con estado ligado a la sesión frente a una autorización específica para Stitch, porque conserva el catálogo agnóstico y evita duplicar consentimiento.

### 4. Catálogo observado, no configuración declarativa ficticia

El catálogo se reconstruye o actualiza únicamente tras handshake y descubrimiento real. `tools/list` y los recursos disponibles se normalizan a metadatos sanitizados; los errores no conservan cuerpos de respuesta ni cabeceras. La UI consume endpoints autenticados de lectura y mutación y usa el ciclo reactivo existente, sin cachear respuestas autenticadas en el service worker.

### 5. Inyección detrás de un único puerto de runtime

Crear un puerto de resolución de perfil MCP que reciba proyecto/Run/agente autorizado, verifique conexión ACTIVA, renueve si procede y devuelva un descriptor efímero sin material persistente innecesario. El adaptador concreto de CLI/socket queda detrás de ese puerto.

El Issue deja pendiente la elección entre argumentos de configuración y socket local de retransmisión. Se conservarán ambas opciones como alternativas de un contrato único, pero Apply no deberá cerrar esa decisión silenciosamente: el gate humano debe seleccionar una, con evidencia de seguridad y compatibilidad para Codex/Antigravity, antes de implementar el adaptador concreto.

### 6. Fail-closed y transacción de estado

Los errores de transporte, autenticación, renovación, handshake o invocación se convierten en un resultado estructurado que bloquea la acción dependiente. La transición de estado, limpieza de caché y publicación de notificación se realiza con la unidad de trabajo PostgreSQL y el broker existente después de commit. Reintentos solo podrán repetir una operación si la observación previa confirma que no se produjo el efecto.

## Risks / Trade-offs

- [Secretos de OAuth2 o API Key en excepciones de librerías] → envolver adaptadores, aplicar `redact_secrets` en cada frontera y probar logs/respuestas con patrones de secretos.
- [El cifrado depende de una clave maestra ausente o rotada] → fallar cerrado, no generar una clave implícita, y documentar la operación de rotación antes de habilitar conexiones nuevas.
- [Un proveedor MCP implementa variantes de HTTP/SSE o stdio] → limitar el Change a los transportes declarados, registrar capacidad no soportada y no presentar una conexión como ACTIVA por un health superficial.
- [La inyección CLI elegida expone credenciales en argv o procesos] → preferir socket local con permisos restringidos cuando el ejecutor lo soporte; si se eligen argumentos, usar credenciales efímeras y verificar que no aparezcan en `/proc`, logs ni evidencia.
- [El catálogo queda obsoleto después de cambios del servidor] → registrar `observed_at`, refrescar durante health/preparación y retirar disponibilidad ante fallo; no inferir herramientas desde configuración histórica.
- [Cambio transversal de alta complejidad] → aplicar revisión independiente de propuesta/código según el contrato rector y exigir E2E real de OAuth2, token, runtime y fail-closed antes del PR.

## Migration Plan

1. Añadir contratos, modelos/repositorios, endpoints y componente Angular sin alterar rutas existentes; ejecutar la migración Alembic únicamente en una base PostgreSQL candidata aislada.
2. Validar invariantes físicas y probar rollback de la migración sin datos MCP; una base con `alembic_version` inconsistente debe fallar cerrado.
3. Habilitar el flujo en preview con servidor MCP de prueba controlado y credenciales efímeras; capturar evidencia del navegador, PostgreSQL, handshake y runtime.
4. Si la verificación falla, retirar la migración y código del candidato mediante la ruta OpenSpec, sin tocar una base productiva ni borrar conexiones activas fuera del Change.

## Owner decisions recorded for Apply

- **1.1 — alcance:** se adopta la opción A: una conexión pertenece a un proyecto, su credencial se cifra con la clave maestra de runtime y el catálogo de herramientas/recursos se conserva en caché separada. Esto minimiza exposición accidental y evita que una conexión activa sea reutilizada por otro proyecto.
- **1.2 — runtime:** se adopta la opción A: un socket local efímero con permisos de propietario y ACL mínima. El puerto devuelve únicamente el perfil efímero al Run/agente autorizado, expira al terminar el Run y no escribe secretos en argv, `/proc`, logs ni evidencia. La resolución falla cerrada si la CLI no puede consumir el puerto.

Estas decisiones son específicas de este Change y no autorizan otros cambios ni sustituyen la política configurable de proveedores.
