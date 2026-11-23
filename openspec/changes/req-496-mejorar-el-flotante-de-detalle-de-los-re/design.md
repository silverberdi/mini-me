# Design

## Context

La motivación está en `proposal.md` y el contrato observable en la delta spec. El Dashboard ya reutiliza `AnalogGaugeComponent` para los cuatro proveedores y le entrega `sublabel` y `detail` desde la proyección existente de `QuotaObservation`. El componente muestra actualmente `sublabel` en un tooltip estrecho sobre la tarjeta y `detail` de forma persistente debajo del reloj. La lógica de porcentaje informado, saldo USD proyectado, referencia visual, estado, fuente y fecha vive en `DashboardComponent` y no debe duplicarse ni trasladarse a la capa visual.

## Goals / Non-Goals

**Goals:**

- Mantener un único patrón visual de detalle para los cuatro relojes.
- Separar el panel del arco, valor y etiqueta, con contenido multilínea legible y usable en los tamaños soportados.
- Reunir en el panel el `sublabel` y el detalle secundario disponible, omitiendo campos ausentes.
- Retirar la presentación persistente debajo de la tarjeta sin retirar la información ni cambiar la proyección.
- Verificar el resultado mediante tests de contrato y un recorrido Playwright de navegador real acotado al Dashboard.

**Non-Goals:**

- No cambiar endpoints, `QuotaObservation`, fuentes de telemetría, proveedores, cálculos, colores primarios, etiquetas ni políticas de cuota.
- No crear un componente por proveedor, un servicio nuevo, una dependencia UI ni una nueva capa de datos.
- No cambiar otras vistas, persistencia, despliegue productivo ni comportamiento de refresco.

## Decisions

1. **Un panel compartido en `AnalogGaugeComponent`.** El componente ya es la única superficie común de los relojes; concentrar allí estructura, separación, wrapping y estados hover/focus evita ramas por proveedor y conserva DRY. La alternativa de construir cuatro tooltips en `DashboardComponent` duplicaría marcado y permitiría divergencias.

2. **El Dashboard conserva la autoridad de datos.** Se reutilizarán `sublabel`, `detail` y las funciones actuales de proyección. El panel combinará los textos ya preparados por el Dashboard y no recalculará porcentajes, saldos o referencias. La alternativa de pasar observaciones crudas al componente aumentaría su responsabilidad y podría duplicar la lógica de cuota.

3. **Detalle multilínea y posicionamiento con espacio propio.** El panel tendrá ancho máximo razonable, wrapping y separación suficiente respecto al contenido del reloj; no dependerá de `whitespace-nowrap` ni de cubrir el arco para ganar espacio. Su anclaje seguirá siendo relativo a la tarjeta compartida, con z-index y contraste existentes o equivalentes.

4. **Presentación interactiva no destructiva.** El detalle se mostrará al pasar el cursor y mediante foco del contenedor, manteniendo el contenido principal siempre visible. En viewport táctil, la verificación se limitará a que la tarjeta no pierda su valor principal ni genere overflow; no se inventará una interacción táctil adicional fuera del Issue.

5. **Retirada segura de la ruta sustituida.** Tras cubrir el nuevo panel, se eliminará el bloque visual persistente de `detail` bajo la tarjeta y sus aserciones exclusivas. Se conservarán los inputs y métodos porque siguen alimentando el panel. No hay escritores, migraciones ni consumidores backend que retirar.

## Risks / Trade-offs

- **[Risk]** Un panel sobre el borde superior puede recortarse en una fila cercana al viewport.
  **Mitigation:** usar wrapping, separación y posicionamiento responsive; cubrir la primera/última tarjeta en Playwright a los anchos declarados.
- **[Risk]** El detalle combinado puede resultar demasiado denso.
  **Mitigation:** jerarquía visual, ancho limitado, saltos de línea y aserciones de texto por campo sin alterar el contenido de la observación.
- **[Risk]** Un test existente puede exigir el detalle bajo la tarjeta.
  **Mitigation:** actualizar solo las aserciones del comportamiento reemplazado y ejecutar nuevamente la suite de contrato y el E2E enfocado después de retirar el markup anterior.

## Migration Plan

No hay migración de datos, API ni despliegue. En Apply se modificará la plantilla compartida y sus consumidores de presentación, se actualizarán pruebas pertinentes y se ejecutará el E2E del Dashboard con Chromium. El rollback es revertir el commit del Change; la telemetría y la lógica de capacidad permanecen intactas.

### Removal Ledger

| Elemento | Acción | Evidencia requerida |
| --- | --- | --- |
| Tooltip estrecho de una línea sobre la tarjeta | REMOVE | diff del componente y E2E de panel legible/separado |
| `detail` persistente debajo del reloj | REMOVE | ausencia de `capacity-secondary-detail` en el DOM y E2E de DeepSeek/OpenRouter |
| `sublabel`, `detail` y funciones de proyección del Dashboard | RETAIN | siguen siendo la fuente única que alimenta el panel |
| API, `QuotaObservation`, telemetría, cálculos y persistencia | RETAIN-WITH-REASON | fuera del alcance; no tienen consumidores reemplazados |

## Open Questions

Ninguna: el Issue define el comportamiento visual y el repositorio ya contiene el componente compartido y los datos necesarios.
