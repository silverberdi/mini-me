## Context

Ver `proposal.md` para la necesidad y `specs/mcp-connections-and-integrations/spec.md` para el contrato observable.

El modelo `MCPConnectionModel` exige actualmente `project_id`; `MCPConnectionService.list` y `MCPRuntimeProfileResolver` filtran por ese proyecto. `OrchestrationCoordinator` recibe una sola conexión MCP opcional por Run, y `ProposalFeasibilityEvaluator` no incluye capacidades MCP en su inventario. La vista Angular carga conexiones usando el proyecto activo. La conexión, el cifrado, OAuth, el descubrimiento, la revocación y el relay efímero ya existen y se deben reutilizar.

## Goals / Non-Goals

**Goals:**
- Añadir conexiones globales y resolverlas entre proyectos sin copiar credenciales.
- Mantener intactas las conexiones locales existentes y su autorización de uso explícita.
- Hacer que las conexiones globales activas estén disponibles a todos los Runs autorizados y a la evaluación de factibilidad.
- Mostrar y administrar el alcance en la vista MCP existente.

**Non-Goals:**
- Añadir proveedores MCP, credenciales compartidas fuera de `mcp_connections` o sincronización de secretos entre proyectos.
- Cambiar la autorización existente de Runs, la política de agentes, el ciclo OpenSpec o la revocación de credenciales.
- Hacer que una conexión local se inyecte automáticamente en todos los proyectos.

## Decisions

1. **Representar alcance global con `project_id IS NULL`.** Hacer nullable la FK existente permite que la fila global sobreviva a la eliminación de un proyecto y conserva integridad referencial para toda fila local. La migración mantiene las filas actuales como locales y mantiene la unicidad local `(project_id, endpoint)`; añade un índice único parcial para que solo exista una conexión global por endpoint. La API deriva `is_global` de `project_id`, sin almacenar dos fuentes de verdad.
   - Alternativa descartada: añadir solo `is_global` y conservar `project_id NOT NULL`; no existe un propietario de proyecto correcto para una conexión organizacional y su borrado podría eliminarla.
   - Alternativa descartada: permitir `project_id` nullable junto con `is_global`; crea combinaciones contradictorias.

2. **Extender el servicio y las rutas MCP existentes.** La lectura por proyecto devuelve filas locales y globales. El registro conserva la ruta existente y acepta `is_global`; el servicio convierte el alcance a `project_id` nulo o al proyecto de la ruta. Las operaciones sobre conexiones globales usan el mismo servicio y validan que la fila sea local al proyecto o global. El OAuth temporal conserva el proyecto iniciador como contexto de retorno, pero la conexión completada conserva alcance global. Las respuestas públicas informan el alcance sin credenciales.
   - Alternativa descartada: duplicar API, servicio o interfaz administrativa para globales; supondría mantener dos caminos para el mismo ciclo de vida.

3. **Resolver capacidades de forma determinista.** El servicio comparte una sola consulta de conexiones elegibles para catálogo, factibilidad y runtime: conexiones locales del proyecto más globales, solo en estado activo. Se deduplica por `(kind, name)` exacto. La conexión local prevalece sobre una global coincidente; en colisiones del mismo alcance gana el menor ID lexicográfico. Así, el runner y la evaluación usan el mismo origen y la misma regla.
   - Alternativa descartada: conservar entradas repetidas para que el agente elija; infringe el contrato de capacidades sin duplicados y vuelve ambigua la invocación.

4. **Inyectar globales y mantener el opt-in local por un puente MCP stdio efímero.** Durante la preparación de una invocación autorizada, resolver y renovar las conexiones globales activas y agregar la conexión local solo cuando fue seleccionada explícitamente. El proceso servidor mini me mantiene un relay por Run en un subdirectorio temporal `0700` bajo `.minime/` del worktree asignado, con el socket `0600`; el agente confinado solo recibe acceso al worktree asignado. Cada solicitud MCP se enruta por `connection_id` a través de `MCPConnectionService`, que conserva el descifrado y la llamada al servidor remoto dentro del proceso de mini me. Un adaptador stdio sin credenciales, iniciado por el CLI, intercambia mensajes JSON-RPC con el relay; solo recibe la ruta del socket. Codex recibe los ajustes MCP efímeros con `-c`; Antigravity recibe el `mcp_config.json` canónico bajo el `HOME` temporal privado que crea la confinación. Ambas configuraciones incluyen solo el comando adaptador, su ruta de socket y el directorio del worktree. Ninguna credencial remota se pasa en argumentos, variables del agente, archivos del worktree o logs. Si hay conexiones MCP elegibles y el CLI no tiene configuración stdio implementada, la preparación falla de forma observable en vez de omitir MCP silenciosamente. Sin conexiones MCP utilizables, se conserva el camino actual sin sesión MCP vacía.
   - Alternativa descartada: inyectar solo cuando se proporcione un `mcp_connection_id`; dejaría a los proyectos dependientes sin herencia automática.
   - Límite: un fallo global requerido debe bloquear esa preparación/invocación de manera observable; una conexión inactiva no es una capacidad disponible y no dispara por sí sola una compuerta humana. El relay vive solo durante la invocación y cierra el socket y elimina su directorio temporal en todos los caminos de salida.

5. **Extender la vista y el evaluador sin crear subsistemas.** El catálogo existente muestra locales y globales con badge; el formulario añade una selección de alcance y sigue usando la API autenticada actual. El inventario de factibilidad agrega referencias observadas a las capacidades globales/locales efectivamente activas, sin inferir herramientas ni modificar las reglas generales de factibilidad.

## Risks / Trade-offs

- **Una conexión global amplía el acceso a credenciales y herramientas a todos los proyectos registrados.** Solo el operador puede cambiar el alcance; cada Run recibe configuración efímera, secretos cifrados y herramientas realmente descubiertas.
- **Una capacidad con el mismo nombre puede representar acciones distintas según servidor.** La precedencia local y el desempate determinista evitan duplicados, aunque el catálogo deberá conservar la asociación a la conexión elegida para diagnosticar la fuente.
- **La migración modifica nulabilidad y unicidad.** Las filas existentes permanecen locales; probar upgrade/downgrade sobre PostgreSQL y evitar editar migraciones ya aplicadas.
- **OAuth global debe completar el retorno sin asociar la conexión al proyecto que inició el consentimiento.** Vincular el estado temporal con el alcance solicitado y verificar proyecto iniciador, hash de estado y expiración antes de activar la fila global.

## Migration Plan

1. Crear migración Alembic que haga nullable `mcp_connections.project_id`, preserve FK y filas existentes, y agregue unicidad parcial del endpoint global junto a los índices locales.
2. Actualizar modelo, servicio, API, runtime y factibilidad para reconocer el alcance nulo; mantener los registros actuales en alcance local.
3. Actualizar vista y verificaciones focalizadas; probar upgrade y rollback en PostgreSQL aislado.

En downgrade, primero comprobar que no existan conexiones globales; si existen, abortar con diagnóstico explícito para evitar perder o reasignar credenciales. Tras retiro autorizado de las filas globales, restaurar `NOT NULL` y la unicidad original.
