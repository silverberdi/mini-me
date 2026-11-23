# Proposal

## Why

Los relojes de capacidad del Dashboard muestran un flotante demasiado estrecho y cercano al reloj, mientras que parte del detalle de DeepSeek y OpenRouter permanece debajo de la tarjeta y compite con su lectura principal. El Issue requiere una presentación única, legible y consistente que mantenga intactos los datos y cálculos existentes.

## What Changes

- Mejorar el flotante compartido de cada reloj de Codex, Antigravity, DeepSeek y OpenRouter para que sea legible, consistente y quede separado visualmente del arco, el valor central y la etiqueta.
- Trasladar al flotante el detalle secundario que hoy se muestra persistentemente debajo de las tarjetas, especialmente para DeepSeek y OpenRouter.
- Presentar en el flotante únicamente los campos disponibles en la observación del proveedor, distinguiendo datos informados, proyecciones visuales, estado, fuente y fecha de observación cuando existan.
- Mantener sin cambios el porcentaje, colores, etiquetas, comportamiento fuera del detalle, proyección USD de referencia y demás lógica de cuota existente.
- Retirar la ruta de presentación secundaria persistente sustituida por el flotante, sin retirar datos, contratos de telemetría ni cálculos.
- Añadir comprobaciones de navegador real para hover/foco, legibilidad, separación del contenido y ausencia del detalle persistente debajo de las tarjetas.

## Capabilities

### New Capabilities

<!-- No se introduce una capacidad independiente; se modifica la capacidad existente de tarjetas de capacidad. -->

### Modified Capabilities

- `pwa-capacity-cards-and-reactive-state`: el detalle de cada reloj pasa a exponerse mediante un flotante compartido y legible, con contenido condicionado por datos disponibles y sin detalle secundario persistente debajo de la tarjeta.

## Impact

- Frontend Angular: `AnalogGaugeComponent` y la plantilla/proyección de capacidad de `DashboardComponent`.
- Pruebas unitarias de contrato y una especificación Playwright enfocada en los cuatro relojes del Dashboard.
- No cambia ningún endpoint, modelo de `QuotaObservation`, fuente de telemetría, proveedor, cálculo de capacidad, política de cuota, persistencia ni dependencia.
- No requiere migración de base de datos, despliegue productivo ni cambios en otras vistas.
