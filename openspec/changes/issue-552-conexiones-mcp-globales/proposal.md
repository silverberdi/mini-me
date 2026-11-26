## Why

Las conexiones MCP actuales pertenecen a un solo proyecto, aunque herramientas organizacionales como Stitch se comparten entre proyectos. Esto obliga a duplicar configuración y credenciales, y hace que la evaluación de propuestas y el runtime no reconozcan capacidades ya autorizadas globalmente.

## What Changes

- Permitir conexiones MCP locales o globales, persistidas en PostgreSQL y con las mismas garantías de cifrado, integridad y revocación.
- Resolver para cada proyecto la unión de sus conexiones locales y las conexiones globales activas, sin duplicar herramientas.
- Reconocer las capacidades globales en la evaluación de factibilidad de OpenSpec y en la preparación autorizada del runtime de agentes.
- Identificar y filtrar por alcance las conexiones globales en el catálogo del Centro de Control y permitir registrar conexiones nuevas con alcance global o de proyecto.

## Capabilities

### New Capabilities

Ninguna.

### Modified Capabilities

- `mcp-connections-and-integrations`: ampliar persistencia, catálogo, factibilidad y uso de conexiones MCP para admitir alcance global y resolución transversal.

## Impact

- Alembic y modelos SQLAlchemy de `mcp_connections`; conservar la FK de proyecto para conexiones locales y representar conexiones globales sin duplicar credenciales.
- `MCPConnectionService`, `MCPRuntimeProfileResolver`, la preparación de Runs en `OrchestrationCoordinator` y `ProposalFeasibilityEvaluator`.
- API `/api/v1/projects/{project_id}/mcp-connections` y la vista Angular `/conexiones-mcp`.
- Pruebas de migración PostgreSQL, resolución backend/runtime, factibilidad y E2E Playwright del catálogo.
