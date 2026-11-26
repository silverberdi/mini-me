## 1. Persistencia y API por alcance

- [x] 1.1 Hacer nullable `mcp_connections.project_id` con migración Alembic reversible de forma segura; conservar las filas actuales como locales y aplicar unicidad para endpoints locales y globales.
- [x] 1.2 Actualizar modelo, servicio y rutas para crear/listar/renovar/revocar/eliminar conexiones locales y globales, incluyendo el retorno OAuth global, sin exponer credenciales; verificar con `pytest tests/test_mcp_connections.py tests/test_mcp_migration.py tests/test_mcp_api.py tests/test_mcp_oauth.py`.

## 2. Resolución y factibilidad

- [x] 2.1 Resolver capacidades observadas locales más globales activas con deduplicación y precedencia determinista; integrar el inventario real con `ProposalFeasibilityEvaluator`.
- [x] 2.2 Verificar capacidades disponibles y ausentes con `pytest tests/test_proposal_feasibility_safe_paths.py tests/test_proposal_feasibility_operator_override.py` y pruebas focalizadas de resolución MCP.

## 3. Runtime de agentes

- [x] 3.1 Preparar un puente MCP stdio temporal por invocación: resolver globales y la conexión local explícita, renovar OAuth, enrutar `tools/list` y `tools/call` por conexión mediante socket Unix `0600`, configurar Codex con `-c` y Antigravity con `mcp_config.json` en `HOME` temporal sin credenciales remotas, y limpiar relay/configuración al cerrar.
- [x] 3.2 Verificar configuración del CLI, `tools/list`, invocación real, resultado, efecto, limpieza y fallo cerrado contra el servidor MCP controlado mediante `pytest tests/test_mcp_runtime_profile.py tests/test_mcp_runtime_integration.py tests/test_mcp_runtime_e2e.py tests/test_mcp_failure_e2e.py`.

## 4. Catálogo del operador

- [x] 4.1 Mostrar conexiones locales y heredadas con badge de alcance; añadir selección de alcance al formulario y filtro global/local en `/conexiones-mcp`.
- [x] 4.2 Verificar registro, visibilidad, filtrado y ausencia de secretos mediante `npx playwright test e2e/mcp-connections-real.spec.ts` desde `frontend/`, con la API y base PostgreSQL aisladas.

## 5. Verificación del Change

- [x] 5.1 Ejecutar migración PostgreSQL y verificaciones focalizadas de persistencia, API, factibilidad y runtime contra el mismo candidato; conservar comandos, resultados y efectos observables.
- [x] 5.2 Ejecutar el E2E Playwright de alcance global con servicios reales del fixture y conservar artefactos reproducibles; confirmar que los datos MCP de proyecto existentes siguen locales y que no hay regresiones en pruebas MCP pertinentes.
