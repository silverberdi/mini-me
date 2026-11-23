# Proposal

## Why

La gráfica de costo liquidado del Dashboard permanece vacía porque las invocaciones reales de agentes no convierten el uso verificable en entradas durables de `budget_ledger`. El cambio debe cerrar esa brecha para que los proyectos reales dispongan de importes observados y trazables, conservando PostgreSQL como única autoridad financiera y sin inferir precios.

## What Changes

- Liquidar cada invocación o etapa que termine con uso y costo verificables, conservando proyecto, proveedor, modelo, importe y marca temporal.
- Persistir la liquidación en `budget_ledger` de forma durable, transaccional e idempotente, sin registrar costos desconocidos como cero ni crear importes sintéticos.
- Integrar los resultados observados de los proveedores soportados por la ejecución real, incluidos DeepSeek Direct, Codex y OpenRouter cuando su contrato de uso permita verificar el costo.
- Mantener `OperationsDashboardService.get_cost_projection` como lectura exclusiva del ledger y hacer observable la transición de `no_data` a `available` con desglose histórico por proveedor/modelo.
- Añadir pruebas enfocadas unitarias, de persistencia y E2E real del trayecto invocación → ledger → API/visualización del Dashboard, incluyendo ausencia de datos, uso no verificable e idempotencia.
- Retirar o desactivar dentro del alcance cualquier writer duplicado, cálculo derivado de tokens o fallback sintético que compita con `budget_ledger`, preservando migraciones e historial legítimos.
- No modificar la arquitectura reactiva ni el TTL del Dashboard de Change #333, y no reintroducir topes artificiales retirados por el Issue #374.

## Capabilities

### New Capabilities

- `durable-cost-settlement`: liquidación transaccional e idempotente de costos observados de invocaciones/etapas y su registro durable en `budget_ledger`.

### Modified Capabilities

- `execution-operations-dashboard`: consumir las nuevas liquidaciones reales para proyectar la serie histórica disponible, manteniendo el estado explícito `no_data` cuando no exista evidencia.

## Impact

- Backend: `NativeOrchestrationCoordinator`, adaptadores/ejecutores de proveedores y servicios de persistencia relacionados con uso, costos y `budget_ledger`.
- Persistencia: modelos, repositorio y migración Alembic únicamente si el esquema actual no alcanza para identidad, precisión, timestamps o idempotencia; no se eliminarán registros históricos.
- API y Dashboard PWA: contrato existente de proyección de costos y actualización reactiva, sin alterar su TTL ni introducir una fuente financiera alternativa.
- Pruebas: suites acotadas del backend y `frontend`/Playwright para la representación visible, con evidencia de invocación, resultado y efectos observables.
