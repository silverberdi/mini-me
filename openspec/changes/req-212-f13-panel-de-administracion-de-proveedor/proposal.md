# Proposal

## Why

El catálogo de proveedores y modelos se encuentra repartido entre constantes, introspección de adaptadores y mapeos de la UI, por lo que el operador no puede descubrir capacidades instaladas ni registrar modelos externos sin modificar Python. F13 necesita una fuente administrativa persistente y verificable para que los cuatro roles usen combinaciones compatibles, manteniendo la separación entre proveedores directos y namespaces de OpenCode.

## What Changes

- Crear un registro PostgreSQL `provider_model_registry` para proveedores, harnesses y modelos descubiertos o personalizados, con identificador canónico, contexto máximo, origen, capacidades y estado de diagnóstico.
- Añadir introspección no destructiva de CLIs soportados (incluidos OpenCode y Ollama) y una operación de refresco idempotente que persista el resultado sin simular disponibilidad.
- Exponer `GET /api/v1/admin/providers/catalog` y `POST /api/v1/admin/providers/models` para consultar el catálogo y crear/editar modelos personalizados, sin persistir secretos.
- Validar que las asignaciones de thinker, implementer, reviewer y backup existen en el catálogo vivo y cumplen sus capacidades: edición para implementer y solo lectura para reviewer.
- Derivar la resolución de modelos de la UI y `model_routes` del catálogo vivo, conservando los consumidores y aliases legacy hasta demostrar su sustitución segura.
- Añadir diagnóstico observable de credenciales, CLI, harness y permisos, con fallos cerrados y sin llamadas destructivas.
- Preservar explícitamente `SUPPORTED_PROVIDER_MODELS`, `SUPPORTED_PROVIDER_EFFORTS`, `DEFAULT_R01_STAGE_PROFILES`, `resolve_stage_profile`, `resolve_cli_invocation`, `agy_model_effort_variant`, `ProjectCatalogService.provider_catalog`, `ProjectCatalogService.agent_catalog`, `ProjectCatalogService.validate_project_profiles`, `OPENCODE_DEEPSEEK_MODELS` y sus aliases.
- No implementar despliegue, scheduler paralelo, generador/emulador de OpenSpec ni eliminar la distinción entre `deepseek` directo y `openrouter/...`/OpenCode.

## Capabilities

### New Capabilities

- `provider-model-registry`: registro persistente, descubrimiento no destructivo, catálogo administrativo, modelos personalizados y diagnóstico de proveedores/harnesses.

### Modified Capabilities

- `project-agent-configuration`: las cuatro asignaciones de roles se validan contra el catálogo vivo y sus capacidades verificadas, y se usan exactamente en el siguiente Run.
- `project-provider-configuration`: el catálogo administrativo incorpora harnesses y modelos sin mezclar conexiones de proyecto ni secretos; las credenciales se diagnostican sin exponerse.

## Impact

- Backend FastAPI, servicios de catálogo/adaptadores, resolución de perfiles y rutas de modelos de la UI.
- Modelos SQLAlchemy/UoW, migración Alembic y repositorio transaccional para `provider_model_registry`; no se crea una cola local de tickets. La migración solo crea esta tabla y sus constraints/índices propios y confirma explícitamente que no ejecutará `ALTER TABLE` sobre tablas del esquema legacy ni modificará conexiones de proyecto, tickets, perfiles existentes o secretos.
- Integraciones locales de OpenCode, Ollama y harnesses configurados; las sondas serán acotadas, no destructivas, con timeout y evidencia de resultado.
- Contratos de configuración de proyecto, validación de roles, endpoints administrativos y pruebas E2E reales que observen invocación, resultado y efecto durable.
- La implementación deberá reutilizar la frontera oficial de OpenSpec/OpenCode y retirar únicamente mapeos demostrablemente obsoletos dentro de este Change.
