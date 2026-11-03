# Design

## Context

La propuesta introduce una fuente viva para modelos sobre el catálogo estático actual, `ProjectCatalogService`, los adaptadores que ya exponen `model_routes` y los perfiles persistidos de proyecto. Las specs del Change son la autoridad de comportamiento; los símbolos legacy tienen consumidores comprobados y no pueden retirarse por una sustitución textual.

## Goals / Non-Goals

**Goals:**

- Mantener un único catálogo de lectura administrativa que combine definiciones estáticas, descubrimiento local y modelos personalizados.
- Persistir únicamente metadata no secreta en PostgreSQL mediante SQLAlchemy/UoW y una migración Alembic reversible.
- Encapsular introspección en adaptadores pequeños por harness, con comandos allowlisted, timeout, salida estructurada, diagnóstico y upsert transaccional.
- Validar perfiles contra capacidades verificadas y conservar rutas nativas de OpenSpec/OpenCode y la identidad separada de DeepSeek directo.
- Probar el recorrido real API → CLI de introspección → PostgreSQL → resolución de perfil, además de errores y concurrencia.

**Non-Goals:**

- Implementar otro runner, scheduler, cola de tickets, generador de OpenSpec o despliegue.
- Guardar tokens, claves, URLs privadas de proyecto o credenciales en el registro.
- Cambiar la autoridad de `project-provider-configuration`, los permisos de merge o el adaptador OpenCode F9; solo integrar sus capacidades observables.
- Retirar los símbolos legacy enumerados en la propuesta sin evidencia de que no tengan consumidores.

## Decisions

### Registro canónico con origen y capacidades

Se usará una fila estable por identidad `(provider_id, harness_id, canonical_model_id)` y campos explícitos para origen, contexto, capacidades, estado, versión y última observación. El origen distingue `static`, `discovered` y `custom`; el upsert no reemplaza una entrada custom con un descubrimiento. Se descarta una tabla por harness y otra por UI porque duplicaría la identidad y haría divergentes las rutas.

La tabla PostgreSQL `provider_model_registry` tendrá la siguiente estructura mínima: `id UUID PRIMARY KEY`, `provider_id TEXT NOT NULL`, `harness_id TEXT NOT NULL`, `canonical_model_id TEXT NOT NULL`, `origin TEXT NOT NULL`, `max_context_tokens INTEGER NULL`, `capabilities JSONB NOT NULL DEFAULT '{}'::jsonb`, `discovery_status TEXT NOT NULL`, `diagnostic_code TEXT NULL`, `diagnostic_summary TEXT NULL`, `observed_cli_version TEXT NULL`, `last_observed_at TIMESTAMPTZ NULL`, `version INTEGER NOT NULL DEFAULT 1`, `created_at TIMESTAMPTZ NOT NULL` y `updated_at TIMESTAMPTZ NOT NULL`. Las constraints serán `pk_provider_model_registry` sobre `id`, `uq_provider_model_registry_identity` sobre `(provider_id, harness_id, canonical_model_id)`, `ck_provider_model_registry_origin` para `static|discovered|custom`, `ck_provider_model_registry_status` para `available|unavailable|blocked`, `ck_provider_model_registry_context_nonnegative`, `ck_provider_model_registry_version_positive` y `ck_provider_model_registry_model_nonempty`. Los índices serán el índice único de identidad generado por `uq_provider_model_registry_identity`, `ix_provider_model_registry_status_updated` sobre `(discovery_status, updated_at)` e `ix_provider_model_registry_origin_provider_harness` sobre `(origin, provider_id, harness_id)`; un índice GIN sobre `capabilities` solo se añadirá si las consultas reales lo justifican durante apply. No se guardarán secretos, URLs privadas ni credenciales en ninguna columna.

### Introspección detrás de una interfaz mínima

Cada harness implementará una operación de descubrimiento read-only que devuelve observaciones tipadas y diagnóstico, mientras el servicio común aplica allowlist, timeout, normalización, idempotencia y persistencia. Se descarta ejecutar comandos arbitrarios enviados por la UI o inferir capacidades por nombre del modelo. Los errores se conservan como diagnóstico no disponible y no habilitan despacho.

### Catálogo administrativo separado de conexiones

El endpoint de catálogo compone metadata del registro y capacidades verificadas, pero resuelve credenciales mediante los mecanismos existentes sin copiarlas al registro ni a la respuesta. El POST de modelos acepta solo metadata validada y usa control de versión para evitar lost updates. Se descarta reutilizar la tabla de conexiones de proyecto porque mezclaría configuración administrativa con secretos y repositorios.

### Compatibilidad gradual de perfiles y UI

La resolución consultará primero la entrada canónica viva y usará los resolvers legacy como compatibilidad controlada cuando no exista una entrada migrada. Las combinaciones se validarán antes de guardar y se congelarán en el perfil del siguiente Run. Se descarta un mapa nuevo paralelo en frontend: `model_routes` y el catálogo deben ser la única fuente de derivación.

### Plan de preservación de identificadores legacy

La transición conservará `SUPPORTED_PROVIDER_MODELS`, `SUPPORTED_PROVIDER_EFFORTS`, `DEFAULT_R01_STAGE_PROFILES`, `resolve_stage_profile`, `resolve_cli_invocation`, `agy_model_effort_variant`, `ProjectCatalogService.provider_catalog`, `ProjectCatalogService.agent_catalog`, `ProjectCatalogService.validate_project_profiles`, `OPENCODE_DEEPSEEK_MODELS` y sus aliases como una fachada de compatibilidad sobre la fuente canónica, no como un segundo catálogo. Antes de cambiar cada consumidor se hará un inventario de imports, llamadas, rutas de UI, perfiles persistidos y pruebas; cada consumidor se migrará a la identidad `(provider_id, harness_id, canonical_model_id)` o a `model_routes`, conservando la firma y el resultado compatible del símbolo mientras exista un caller.

El backfill estático alimentará la fachada y el registro sin reescribir perfiles ni eliminar aliases. Los resolvers legacy delegarán en el resolver canónico cuando haya una entrada viva y conservarán el fallback acotado para datos aún no migrados; toda ausencia, ruta desconocida o capability no verificada fallará cerrada. Cada símbolo tendrá una prueba de contrato/regresión que compruebe disponibilidad, alias, resolución y separación entre DeepSeek directo y el namespace OpenCode, además de una prueba de integración que demuestre que el siguiente Run recibe los valores canónicos exactos. Solo después de que el inventario demuestre cero consumidores activos, la suite de regresión pase y exista evidencia del reemplazo equivalente, se podrá retirar un mapeo interno dentro de este Change; los nombres públicos y aliases se conservan si siguen formando parte del contrato. El diff y las pruebas registrarán qué rutas se mantienen, cuáles delegan y cuáles, si procede, quedan retiradas.

### Migración y retiro seguro

La migración crea la tabla con índices de identidad, versionado y timestamps; no altera ni elimina tablas de configuración existentes. Un backfill idempotente transforma las constantes actuales en entradas `static` solo cuando no existe una custom. El rollback elimina únicamente filas creadas por el backfill y la tabla nueva tras detener consumidores, nunca datos de proyectos ni secretos. Los mapeos legacy se retiran solo después de pruebas de consumidores y evidencia de reemplazo.

La migración no ejecutará `ALTER TABLE` sobre tablas del esquema legacy, ni añadirá columnas, restricciones o índices a conexiones de proyecto, tickets, perfiles existentes o cualquier otra tabla preexistente. Toda compatibilidad con ese esquema se resolverá mediante lectura/adaptadores y la única escritura estructural de este Change será la creación de `provider_model_registry` y sus índices/constraints propios.

## Risks / Trade-offs

- **[CLI local ausente, lento o con salida incompatible]** → timeout estricto, parser versionado, diagnóstico por harness y estado no disponible; nunca marcar disponibilidad por defecto.
- **[Una capability declarada incorrectamente habilita un rol peligroso]** → capacidades verificables separadas para edición y lectura, validación fail-closed y E2E con implementer/reviewer.
- **[Carreras entre refresh y edición custom]** → transacción, clave de identidad, versionado optimista y reglas que no sobrescriben custom con discovery.
- **[Ruptura de consumidores legacy]** → inventario de callers, pruebas de regresión y retiro únicamente dentro del Change con evidencia.
- **[Exposición accidental de secretos en diagnóstico]** → DTOs allowlisted, redacción central y pruebas que inspeccionen respuestas, logs y persistencia.

## Migration Plan

1. Aplicar la migración en una transacción y registrar el backfill de metadata estática sin ejecutar CLIs.
2. Desplegar el repositorio/servicio y endpoints en modo compatible; refresco explícito del operador, sin activación automática de proveedores.
3. Validar catálogo, perfiles y resolución contra un harness real; observar invocación, resultado y filas persistidas.
4. Activar la derivación viva por proyecto después de validar perfiles; conservar fallback legacy solo como compatibilidad instrumentada.
5. Retirar mapeos muertos demostrados y repetir pruebas de regresión. Para rollback, desactivar lecturas vivas, revertir la migración solo si no hay datos que conservar y restaurar la resolución compatible.

## Open Questions

No hay preguntas diferibles que cambien el contrato: los comandos concretos por CLI y el formato exacto de diagnóstico pueden resolverse durante apply respetando las allowlists y escenarios de estas specs.
