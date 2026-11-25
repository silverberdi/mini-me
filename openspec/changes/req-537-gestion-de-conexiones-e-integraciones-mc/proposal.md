# Proposal

## Why

Los agentes CLI y los servicios desasistidos no pueden completar consentimientos OAuth ni depender de edición manual de archivos para usar servidores MCP. El Centro de Control necesita un punto operativo autenticado que permita registrar, autorizar, comprobar, descubrir y revocar conexiones una vez, manteniendo las credenciales confinadas a mini me y disponibles de forma segura durante un Run.

La autorización de este Change proviene de la solicitud expresa del operador que lo dispara; una etiqueta `disabled` del Issue sin esa validación expresa debe seguir bloqueando Propose y ejecución.

## What Changes

- Añadir una entrada lateral dedicada «Conexiones MCP» y la ruta Angular `/conexiones-mcp`, separada de «Administración».
- Añadir un catálogo agnóstico de servidores MCP con estados conectado, desconectado y error, acciones de conexión/revocación y capacidades descubiertas.
- Añadir endpoints FastAPI autenticados para registrar, autorizar, validar, consultar, renovar y revocar conexiones MCP mediante HTTP/SSE y stdio, según la capacidad declarada por cada integración.
- Implementar flujos OAuth2 interactivos para proveedores compatibles y flujos de API Key/Bearer token con saludo inicial MCP, sin dejar secretos en frontend, repositorio, logs ni repositorio destino.
- Persistir de forma cifrada y vinculada a PostgreSQL las credenciales necesarias, el estado de conexión y el catálogo mínimo de herramientas/recursos; evolucionar el esquema con una migración Alembic reversible y mínima.
- Descubrir y registrar capacidades tras handshake, incluido `tools/list`, y exponer al operador únicamente metadatos seguros y diagnósticos sanitizados.
- Integrar la resolución/renovación de credenciales y la inyección efímera de configuración MCP en el perfil de invocación de agentes autorizados durante un Run, sin interacción de navegador.
- Aplicar fail-closed ante credenciales revocadas, endpoints inaccesibles, handshake fallido o herramienta no disponible; registrar el diagnóstico y notificar al operador sin simular éxito.
- Eliminar cualquier ruta o control de conexión MCP duplicado que pudiera quedar dentro de Administración dentro del alcance de este Change.

## Capabilities

### New Capabilities

- `mcp-connections-and-integrations`: gestión autenticada de conexiones MCP, OAuth2 y credenciales estáticas, persistencia segura, descubrimiento de herramientas/recursos, revocación, renovación, fail-closed e inyección para ejecuciones desasistidas.

### Modified Capabilities

- Ninguna. La nueva entrada de navegación amplía el shell existente, pero no sustituye los contratos de las cinco vistas actuales ni modifica sus requisitos semánticos.

## Impact

- `frontend/src/app/app.component.ts`, `frontend/src/app/app.routes.ts` y un nuevo componente de feature para la vista de conexiones MCP.
- `src/minime/api/app.py`, servicios/adaptadores MCP nuevos o reutilizados, modelos/repositorios SQLAlchemy y una migración Alembic bajo `alembic/versions/`.
- Contratos de invocación de agentes y preparación de perfiles de Run, respetando la configuración de roles/proveedores existente y sin hardcodear un proveedor MCP.
- Pruebas unitarias, de integración PostgreSQL y Playwright focalizadas en esta capability; las pruebas de navegador deberán demostrar navegación y estados observables con un servidor MCP de prueba controlado, y la verificación de OAuth2/credenciales y runtime deberá aportar evidencia de invocación, resultado y efectos reales.
- Antes de Apply quedan como decisiones del propietario: el esquema mínimo definitivo de `mcp_connections`/`mcp_tools_cache` y el mecanismo exacto de inyección en las CLI (argumentos de configuración o socket local de retransmisión). El diseño deberá mantener ambas opciones aisladas detrás de contratos mínimos hasta resolverlas.
