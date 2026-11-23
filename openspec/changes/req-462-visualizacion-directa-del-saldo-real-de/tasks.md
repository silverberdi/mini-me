# Tasks

## 1. Proyección de saldo y componente visual

- [x] 1.1 Actualizar la proyección del Dashboard para priorizar un `balance` finito de DeepSeek cuando `remaining_percent` sea nulo, formatear el valor con su `currency` observada y conservar el estado desconocido cuando no haya valor verificable; verificar con pruebas unitarias los casos balance, porcentaje, valor ausente, cero y valor no finito.
- [x] 1.2 Extender `app-analog-gauge` con una presentación textual sin escala para balances monetarios, manteniendo intacta la ruta porcentual de los demás proveedores; verificar que un balance no muestra `%`, `—`, ni una aguja derivada de un `max` artificial y que los porcentajes existentes siguen mostrando su unidad y arco.
- [x] 1.3 Retirar la ruta visual sustituida que hacía del `sublabel`/hover la única representación del saldo y revisar imports, bindings y estilos para no dejar callers o fallback duplicados; verificar mediante búsqueda estática y pruebas de regresión que el balance solo usa la nueva autoridad visible.

## 2. Validación de interfaz y regresión

- [x] 2.1 Añadir o adaptar el check frontend declarado para comprobar en un navegador real que una respuesta observable de `/api/v1/providers/quotas` con `provider: deepseek`, `balance: 20.18`, `currency: USD` y `remaining_percent: null` renderiza `$20.18 USD` dentro de la tarjeta sin depender de hover; verificar también que el viewport móvil no produce overflow horizontal.
- [x] 2.2 Añadir el escenario negativo de navegador para una observación DeepSeek sin `balance` ni `remaining_percent`, comprobando el estado desconocido sin porcentaje ni saldo inventado; verificar el resultado con `npm --prefix frontend run test:e2e` mediante el ejecutor configurado.
- [x] 2.3 Ejecutar los checks frontend declarados y la suite pertinente tras retirar la ruta antigua, incluyendo `npm --prefix frontend run test` y `npm --prefix frontend run test:e2e -- dashboard-capacity-balance.spec.ts`; conservar salida, código de retorno y evidencia observable de la tarjeta para Verify.
  - Evidencia Apply candidate-bound: `HEAD=1fe00429439fbbbb962bdad344e41748156a2731`. `npm --prefix frontend run test` pasó 73/73 con código 0 y `npm --prefix frontend run test:e2e -- dashboard-capacity-balance.spec.ts` pasó 2/2 en Chromium real con código 0. La E2E observó `$20.18 USD` directamente, sin `%` ni `—`, sin overflow horizontal móvil, y el caso sin balance/porcentaje mostró estado desconocido.

## 3. Límites y evidencia del Change

- [x] 3.1 Verificar que el diff no modifica `/api/v1/providers/quotas`, la frecuencia/cache de sondeo, SSE, persistencia ni topes diarios artificiales; documentar la inspección de consumidores y el estado final del ledger de retirada.
- [x] 3.2 Capturar evidencia ligada al SHA candidato: archivos modificados, pruebas ejecutadas, resultado visible del caso `$20.18 USD`, ausencia de `%`/`—` y caso desconocido; verificar que la evidencia distingue checks unitarios de E2E real y está lista para el workflow OpenSpec Verify.
  - Evidencia Apply candidate-bound: `HEAD=1fe00429439fbbbb962bdad344e41748156a2731`. Archivos del Change: `frontend/src/app/features/dashboard/dashboard.component.ts`, `frontend/src/app/shared/analog-gauge.component.ts`, `frontend/tests/dashboard-capacity-balance.test.mjs`, `frontend/e2e/dashboard-capacity-balance.spec.ts` y artefactos OpenSpec/static. Unit tests: 73/73, código 0. E2E real Playwright + Chromium + Uvicorn/FastAPI: 2/2, código 0; observó `$20.18 USD` directamente, sin `%`, sin `—`, sin overflow horizontal móvil, y el caso sin balance/porcentaje mostró estado desconocido sin saldo inventado. `git diff --check` pasa.
