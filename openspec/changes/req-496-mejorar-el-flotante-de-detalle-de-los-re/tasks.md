# Tasks

## 1. Inventario y contrato visual

- [x] 1.1 Confirmar en `AnalogGaugeComponent`, `DashboardComponent` y las pruebas de capacidad los consumidores del tooltip y del detalle persistente; verificar que no existen escritores, endpoints o cálculos adicionales dentro del alcance mediante búsqueda estática y registrar el resultado en el candidato.
- [x] 1.2 Actualizar las aserciones de contrato necesarias para expresar el panel compartido, los datos disponibles y la ausencia del detalle persistente debajo; verificar con `node --test frontend/tests/dashboard-capacity-balance.test.mjs`.

## 2. Implementación frontend

- [x] 2.1 Reestructurar el detalle en `AnalogGaugeComponent` como un único panel compartido, multilínea, legible y separado del arco, valor central y etiqueta, conservando hover/foco y la estructura común; verificar mediante el build de frontend.
- [x] 2.2 Conectar en el panel los valores `sublabel` y `detail` ya entregados por `DashboardComponent`, retirando solo el bloque persistente debajo de la tarjeta y sin duplicar o modificar la lógica de cuota; verificar con `node --test frontend/tests/dashboard-capacity-balance.test.mjs`.
- [x] 2.3 Mantener la presentación primaria de los cuatro relojes y comprobar que el diff no modifica endpoints, `QuotaObservation`, fuentes, cálculos ni políticas; verificar con revisión estática del diff y `node --test frontend/tests/dashboard-capacity-balance.test.mjs`.

## 3. Verificación de navegador real y cierre técnico

- [x] 3.1 Añadir o ajustar el escenario Playwright enfocado en los cuatro relojes para hover/foco, contenido específico por proveedor, separación visual, responsive y ausencia del detalle debajo; verificar con `npm --prefix frontend run test:e2e -- e2e/dashboard-capacity-balance.spec.ts` usando Chromium real y evidencia observable del resultado.
- [x] 3.2 Ejecutar la verificación de integración acotada del frontend y confirmar que el artefacto compila; verificar con `npm --prefix frontend run build` y repetir `npm --prefix frontend run test:e2e -- e2e/dashboard-capacity-balance.spec.ts` después de retirar el markup antiguo.
- [x] 3.3 Validar la coherencia final del Change y comprobar el Removal Ledger; verificar con `openspec validate req-496-mejorar-el-flotante-de-detalle-de-los-re --strict` y evidencia del diff/candidato que no quedan referencias activas al detalle persistente sustituido.
