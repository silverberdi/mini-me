# Design

## Context

La propuesta modifica la capacidad existente `pwa-capacity-cards-and-reactive-state`; la delta completa está en `specs/pwa-capacity-cards-and-reactive-state/spec.md`. El backend ya expone `QuotaObservation.balance`, `currency` y `remaining_percent`, y `RefreshService` consume `/api/v1/providers/quotas` y actualizaciones SSE. El inventario actual muestra que `dashboard.component.ts` envía siempre `unit="%"` al `app-analog-gauge` de DeepSeek, mientras `deepseekValue` solo lee `remaining_percent`; el balance observado solo se incluye en `deepseekSublabel`. `analog-gauge.component.ts` dibuja un arco escalado por `value/max` y muestra `—` para `null`.

Restricciones: no cambiar el sondeo ni el contrato backend, no persistir nuevos datos, no crear topes ficticios, mantener porcentajes verificados para los demás proveedores y cumplir la validación de UI en navegador real mediante el ejecutor configurado.

## Goals / Non-Goals

**Goals:**

- Hacer que el saldo monetario observado de DeepSeek sea el valor principal visible en la tarjeta.
- Mantener una ruta única de presentación: porcentaje cuando existe porcentaje verificado; balance monetario cuando existe balance finito sin porcentaje; desconocido cuando no existe valor verificable.
- Permitir que el componente visual comunique explícitamente cuándo no hay escala porcentual, sin posicionar una aguja contra un máximo inventado.
- Preservar accesibilidad, legibilidad responsive y metadatos de observación secundarios.
- Retirar la ruta sustituida que relegaba el balance al tooltip y la unidad rígida `%` para DeepSeek.

**Non-Goals:**

- Cambiar `/api/v1/providers/quotas`, el adaptador DeepSeek, la frecuencia de consulta, SSE o el cache de telemetría.
- Calcular porcentajes, límites, resets o estados operativos no informados por el proveedor.
- Cambiar las tarjetas de Codex, Antigravity u OpenRouter salvo el soporte reutilizable necesario del componente.
- Migrar PostgreSQL, desplegar producción o introducir una dependencia frontend.

## Decisions

1. **Reutilizar `QuotaObservation` y el componente existente.** El frontend ya tiene los campos `balance` y `currency`; se modifica la proyección de Dashboard y se amplía el contrato visual mínimo del gauge. Esto evita una API paralela o un modelo duplicado. Se descarta añadir un endpoint o normalizar balances en backend porque el valor observado ya llega correctamente.

2. **Prioridad explícita del valor.** Para DeepSeek, un balance numérico finito será la fuente del valor principal cuando `remaining_percent` sea nulo; si hay porcentaje verificado, se conserva la representación porcentual existente; si faltan ambos, se muestra desconocido. No se mezclan balance y porcentaje en una sola escala. Se descarta convertir USD a porcentaje porque no existe denominador autorizado.

3. **Representación sin escala para balances.** El gauge debe admitir un modo de display textual monetario con unidad incluida en el texto (`$20.18 USD`) y sin arco de progreso derivado de `max`. Los proveedores porcentuales siguen usando `max=100`, `%` y su arco actual. Se descarta usar `max=balance`, porque produciría una lectura visual engañosa de 100% para cualquier saldo.

4. **Visibilidad directa y tooltip secundario.** El valor monetario se renderiza dentro de la tarjeta con estilos responsive y el tooltip puede conservar detalles de fuente/fecha. La tarjeta no requiere hover ni interacción para conocer el saldo. Se descarta usar solo `aria-label` o tooltip como sustituto del contenido visible.

5. **Pruebas proporcionales con navegador real.** Se añadirán pruebas unitarias del formateo/prioridad y un escenario Playwright que cargue una respuesta observable de cuotas con `deepseek`, `balance: 20.18`, `currency: USD`, `remaining_percent: null`, y compruebe el DOM visible en un viewport de escritorio y uno móvil. El ejecutor configurado correrá `npm --prefix frontend run test:e2e` y los checks frontend declarados; no se asignan al operador navegación, asincronía, viewport ni concurrencia.

### Censo y retirada segura

| Superficie | Acción | Evidencia esperada |
| --- | --- | --- |
| `dashboard.component.ts` (`deepseekValue`, `deepseekSublabel`, bindings de DeepSeek) | MIGRATE/REMOVE | La tarjeta usa la prioridad balance/porcentaje y el balance deja de ser tooltip-only. |
| `analog-gauge.component.ts` (`value`, `max`, `unit`, arco y texto central) | MIGRATE | Modo textual sin escala para balances; porcentajes sin regresión. |
| `core/models.ts` (`QuotaObservation`) | RETAIN | Los campos observados ya cubren el contrato; no se añade writer. |
| `RefreshService` y `/api/v1/providers/quotas` | RETAIN | La fuente, cache, frecuencia y SSE permanecen sin cambios; se verifica ausencia de llamadas nuevas. |
| PostgreSQL/Alembic | NONE | El cambio es de proyección UI y no crea ni modifica persistencia. |
| Tooltip que contiene el balance | REMOVE-AS-PRIMARY / RETAIN-AS-METADATA | Se conserva la fuente/fecha como detalle secundario, pero ya no es la única representación del saldo. |

## Risks / Trade-offs

- **[Risk]** Un balance demasiado largo puede desbordar la tarjeta en móvil. → **Mitigation:** estilos responsive, formato monetario acotado y prueba Playwright en viewport móvil sin overflow horizontal.
- **[Risk]** Un proveedor podría entregar un balance no finito o sin moneda. → **Mitigation:** aceptar solo números finitos; usar la moneda observada cuando exista y mostrar estado explícito no disponible si el valor no es verificable, sin inventar una unidad.
- **[Risk]** El componente compartido podría alterar porcentajes existentes. → **Mitigation:** conservar el camino `value/max/unit` para Codex, Antigravity y OpenRouter y cubrir ambos modos en pruebas.
- **[Risk]** Una prueba con datos simulados podría confundirse con E2E real. → **Mitigation:** el plan exige browser check declarado ejecutado contra la aplicación y el endpoint/read model observable, registrando comando, resultado y efectos; fixtures aislados solo cubren lógica unitaria.

## Migration Plan

No hay migración de datos ni cambio de API. En Apply se implementa la nueva proyección, se comprueba el flujo con pruebas unitarias y navegador real, y después se elimina la ruta visual antigua que trataba el saldo como sublabel exclusivo. El rollback es revertir el commit del Change; no requiere restaurar datos ni reiniciar el sondeo.

## Open Questions

Ninguna: el Issue fija el saldo observado, la moneda, la ausencia de denominador y el límite de no modificar el backend.
