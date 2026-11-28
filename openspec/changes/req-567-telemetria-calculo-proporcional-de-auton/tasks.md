# Tasks

## 1. Inventario y contrato de evidencia

- [x] 1.1 Censar callers, repositorios, writers, DTOs, endpoint y consumidores frontend de `TemporalMultiseriesTelemetryService`, y registrar en el diff del Change qué se reutiliza, modifica y retira; verificar con `rg -n "TemporalMultiseriesTelemetryService|temporal_telemetry|autonomy_outcomes|operator_needed" src tests frontend`.
- [x] 1.2 Definir el mapeo observable de etapas, gates de gobernanza, bloqueos técnicos, acciones de operador y recuperación autónoma contra la evidencia durable existente; verificarlo con fixtures que contengan al menos un Change 5/6 y un caso ambiguo fail-closed.

## 2. Cálculo proporcional y reproyección backend

- [x] 2.1 Modificar `src/minime/services/temporal_multiseries_telemetry_service.py` para calcular autonomía por etapas recorridas, acotar el resultado a 0–100 y conservar no-data/unverified; verificar con pruebas enfocadas de governance-only, operador técnico, recuperación, retries y evidencia incompleta.
- [x] 2.2 Exponer outcomes y contadores suficientes para explicar etapas autónomas, gobernanza, bloqueo técnico, acción de operador y runs elegibles sin romper los consumidores válidos del DTO; verificar serialización de la respuesta de telemetría y ausencia de campos inventados.
- [x] 2.3 Hacer que la proyección recorra todos los runs históricos elegibles y todos los proyectos representados desde los repositorios PostgreSQL existentes, sin backfill destructivo ni nueva fuente de verdad; verificar repetición estable y estado durable idéntico antes/después en la prueba de reproyección.
- [x] 2.4 Mantener la pureza del GET y de las consultas transitivas: sin commit, evento, insert/update/delete ni lock de escritura durante la reproyección; verificar con `pytest tests/test_temporal_multiseries_telemetry.py tests/test_dashboard_security.py -q` y una aserción de estado antes/después.

## 3. Dashboard y consumidores

- [x] 3.1 Adaptar los modelos y el resumen de autonomía del Dashboard únicamente para representar la proporción y los outcomes diferenciados, preservando las dimensiones temporal, costo y tiempo y el resumen de Trabajo Actual; verificar con `npm --prefix frontend run test -- --test-name-pattern=telemetry` o la prueba unitaria frontend específica creada para este Change.
- [x] 3.2 Cubrir la invocación real del endpoint autenticado y la representación en Chromium de la gráfica histórica multi-proyecto, incluyendo valor mayor que cero para 5/6, etiqueta de gobernanza y estado no-data; verificar con `npm --prefix frontend run test:e2e -- e2e/dashboard-temporal-telemetry.spec.ts` usando el runtime configurado.

## 4. Retirada segura y verificación del valor

- [x] 4.1 Migrar y eliminar el branch binario `operator_needed` ⇒ 0 y actualizar las aserciones antiguas solo después de que el cálculo proporcional esté cubierto; verificar con `rg -n "operator_needed.*0|value == 0\.0|100\.0" tests/test_temporal_multiseries_telemetry.py src/minime/services/temporal_multiseries_telemetry_service.py` y la ausencia de callers obsoletos.
- [x] 4.2 Ejecutar la suite backend acotada completa del Change después de la retirada y conservar evidencia de resultado, endpoint, efectos y SHA: `pytest tests/test_temporal_multiseries_telemetry.py -q`.
- [x] 4.3 Ejecutar la E2E de navegador del Dashboard después de la retirada y conservar evidencia observable de respuesta, gráfica, outcomes y preservación de Trabajo Actual: `npm --prefix frontend run test:e2e -- e2e/dashboard-temporal-telemetry.spec.ts`.
- [x] 4.4 Validar el Change con la autoridad nativa de OpenSpec y comprobar que proposal, specs, design y tasks quedan completos: `openspec validate req-567-telemetria-calculo-proporcional-de-auton --strict` y `openspec status --change req-567-telemetria-calculo-proporcional-de-auton`.
