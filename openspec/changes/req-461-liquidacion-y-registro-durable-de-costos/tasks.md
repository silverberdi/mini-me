# Tasks

## 1. Inventario y contrato de persistencia

- [x] 1.1 Censar en `NativeOrchestrationCoordinator`, ejecutores/adaptadores de Codex, DeepSeek y OpenRouter, repositorio/modelo Alembic de `budget_ledger`, `OperationsDashboardService` y sus tests los writers, consumidores, claves de uso y cálculos de costo existentes; verificar el inventario con búsquedas estáticas y dejar el Removal Ledger del design actualizado.
- [ ] 1.2 Confirmar la forma durable mínima para proveedor, modelo opcional, importe, precisión, timestamp, fuente e identidad idempotente; si falta una columna o restricción, crear una migración Alembic aditiva y verificarla contra las seis filas históricas sin backfill inventado.

## 2. Liquidación del resultado de ejecución

- [x] 2.1 Implementar el contrato pequeño de liquidación que acepte únicamente uso y monto observados, normalice proyecto/proveedor/modelo/timestamp y rechace evidencia incompleta; verificar con pruebas unitarias de monto ausente, timestamp ausente, proveedor desconocido y cero sintético.
- [ ] 2.2 Integrar la liquidación transaccional con la finalización real de invocaciones/etapas en `NativeOrchestrationCoordinator` y los adaptadores que expongan costo verificable; verificar que el resultado de ejecución y la entrada de `budget_ledger` se comprometen juntos.
- [x] 2.3 Hacer idempotente la escritura por identidad de uso y segura ante concurrencia/reanudación; verificar con dos finalizaciones del mismo identificador que existe una sola entrada y que el segundo intento devuelve la liquidación existente.
- [ ] 2.4 Preservar explícitamente outcomes no liquidables o ambiguos para reconciliación sin registrarlos como cero; verificar que un fallo de commit no aparece como costo `available` en la lectura del Dashboard.

## 3. Proyección y experiencia del Dashboard

- [x] 3.1 Ajustar solo los mapeos necesarios de `OperationsDashboardService.get_cost_projection` para aceptar las nuevas entradas y conservar `no_data`, precisión, timestamp, proveedor y modelo; verificar que los GET siguen siendo puros y que no se crea una autoridad/caché alternativa.
- [ ] 3.2 Implementar o actualizar la prueba de integración API con PostgreSQL que inserte liquidaciones observadas de DeepSeek Direct y OpenRouter y verifique `status="available"`, series históricas y desglose por modelo, además de `no_data` sin registros.
- [ ] 3.3 Asignar al ejecutor configurado la prueba de navegador real del Dashboard y verificar con Playwright el trayecto ledger → endpoint → gráfica visible, la transición de estado vacío a serie y la ausencia de atribución desde tokens sin precio; ejecutar únicamente el spec E2E pertinente.

## 4. Retirada segura y regresión

- [ ] 4.1 Retirar, tras demostrar la ruta nueva, cualquier writer duplicado, estimación por tokens o fallback sintético alcanzable identificado en el Removal Ledger; verificar con búsqueda de callers, diff y pruebas negativas que solo `budget_ledger` suministra costos.
- [x] 4.2 Ejecutar las pruebas backend acotadas del módulo de ledger y Dashboard (`python -m pytest tests/test_budget_api.py tests/test_budget_service.py tests/test_dashboard_cost.py tests/test_dashboard_cost_postgres_e2e.py tests/test_postgres_budget_concurrency.py`) y corregir regresiones sin ejecutar migraciones o despliegues productivos.
- [ ] 4.3 Ejecutar las comprobaciones frontend acotadas (`npm --prefix frontend run test -- tests/dashboard-cost.test.mjs`) y el spec browser pertinente (`npm --prefix frontend run test:e2e -- dashboard-active-change.spec.ts` o el nuevo spec de costo que el Apply añada) con el ejecutor configurado; conservar evidencia observable de invocación, resultado, filas del ledger, respuesta API y visualización.
- [ ] 4.4 Verificar el candidato final contra el SHA exacto, el contrato del Change, el Removal Ledger y los escenarios de ambas specs; confirmar que no se modificaron `RefreshService.DASHBOARD_CACHE_TTL_MS`, topes artificiales ni despliegues, y dejar el Change listo para Verify nativo.
