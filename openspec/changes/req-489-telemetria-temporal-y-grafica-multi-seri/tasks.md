# Tasks

## 1. Inventario y contrato de datos

- [x] 1.1 Censar en `src/minime/services/dashboard_service.py`, servicios/repositorios de eficiencia y liquidación, `frontend/src/app/features/dashboard/` y pruebas todos los writers/callers de la gráfica actual de últimos cinco runs; registrar en el Removal Ledger qué se retira, migra o conserva y verificarlo con búsquedas estáticas reproducibles.
- [x] 1.2 Definir el payload temporal único (dimensión, ventana, granularidad, eje ordenado, series Global/proyecto, unidades, calidad/no-data y metadatos de exclusión) dentro del contrato existente del Dashboard; verificarlo con pruebas de contrato que rechacen puntos sin timestamp o fuente verificable.

## 2. Proyección backend

- [x] 2.1 Implementar la consulta/agregación temporal reutilizando Run, eventos/intervalos, gates humanos, proyectos y liquidaciones verificadas, con ventana por defecto de 30 días y buckets diarios/semanales deterministas; verificarlo con `pytest tests/test_temporal_multiseries_telemetry.py -q` cubriendo orden, límites, Global y series por proyecto.
- [x] 2.2 Calcular autonomía continua acotada a 0–100 con penalización de reintentos, bucles y rescates técnicos, separando gobernanza legítima; verificarlo con `pytest tests/test_temporal_multiseries_telemetry.py -q` mediante casos comparables con y sin retrabajo.
- [x] 2.3 Calcular tiempos solo con intervalos activos de máquina y excluir esperas de gates humanos, conservando metadatos de exclusión; verificarlo con `pytest tests/test_temporal_multiseries_telemetry.py -q` en un caso con ambas clases de intervalo.
- [x] 2.4 Integrar costo liquidado en la misma proyección sin derivarlo de tokens ni crear otra autoridad; verificar no-data explícito cuando solo existan tokens con `pytest tests/test_temporal_multiseries_telemetry.py -q`.
- [x] 2.5 Aplicar sanitización, autenticación y el refresh existente al nuevo read model sin persistir estado de interacción; verificar el endpoint con el test de contrato backend pertinente del Dashboard y una respuesta sin secretos.

## 3. Gráfica Angular e interacción

- [x] 3.1 Adaptar `frontend/src/app/features/dashboard/` para consumir el payload temporal y renderizar eje común, Global prominente, líneas por proyecto, unidades y estados sin datos sin modificar la tarjeta de Trabajo Actual; verificar con `npm --prefix frontend run test -- dashboard` o el archivo de test Dashboard específico que exista tras el inventario.
- [x] 3.2 Implementar leyenda accesible y reutilizable para toggle, `Aislar`/Solo, restauración y hover con atenuación, manteniendo identidad por etiqueta/color/indicador adicional; verificar los estados de interacción en el test unitario del componente y en navegador real.
- [x] 3.3 Mantener la misma interacción al alternar Autonomía, Tiempos de Entrega y Costo liquidado, incluyendo no-data y ausencia de datos parciales; verificarlo en la especificación Playwright específica del Change.

## 4. E2E real y retiro seguro

- [x] 4.1 Añadir una prueba Playwright acotada, por ejemplo `frontend/e2e/dashboard-temporal-telemetry.spec.ts`, que cargue el Dashboard en Chromium, observe el payload y DOM reales, y demuestre Global/proyectos, eje temporal, toggle, Solo, hover, tres dimensiones, no-data y preservación del resumen Trabajo Actual; verificar con `npm --prefix frontend run test:e2e -- e2e/dashboard-temporal-telemetry.spec.ts`.
- [x] 4.2 Ejecutar el escenario E2E con datos verificables de PostgreSQL/fixtures del proyecto y conservar evidencia observable de invocación, resultado y efectos, sin presentar mocks de red aislados como prueba de integración real; verificar exit code 0 y artefactos Playwright del spec acotado.
- [x] 4.3 Migrar todos los consumidores del gráfico de cinco runs a la nueva autoridad, retirar solo código, estilos, campos y pruebas exclusivas ya obsoletos, y documentar cualquier histórico que deba conservarse; verificar ausencia de callers duplicados con `rg` y revisar el diff del candidato.
- [x] 4.4 Repetir después del retiro las pruebas backend y navegador pertinentes: `pytest tests/test_temporal_multiseries_telemetry.py -q` y `npm --prefix frontend run test:e2e -- e2e/dashboard-temporal-telemetry.spec.ts`; verificar que la ausencia de la ruta vieja no reduce la cobertura del contrato nuevo.
