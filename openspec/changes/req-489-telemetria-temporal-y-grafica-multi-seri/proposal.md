# Proposal

## Why

La telemetría del Dashboard presenta ejecuciones puntuales recientes y una autonomía binaria, por lo que no permite comparar tendencias entre proyectos ni distinguir procesamiento de máquina de esperas humanas. El Issue #489 necesita una lectura temporal común y honesta de autonomía, tiempos activos y costos para que el operador pueda investigar el comportamiento del portafolio sin perder la vista del Trabajo Actual.

## What Changes

- Añadir al Dashboard una serie histórica temporal multi-serie para una ventana acotada (por defecto, últimos 30 días) con eje común por días o semanas.
- Dibujar una serie prominente `Global (Todos los proyectos)` y una serie por proyecto con color de identidad estable, sin inventar puntos cuando falten datos.
- Calcular autonomía como índice continuo entre 0% y 100%, penalizando retrabajo y bucles técnicos sin confundir gobernanza humana legítima con rescates de ingeniería.
- Exponer tiempo de entrega como tiempo activo de procesamiento de máquina, separado de las esperas en gates humanos.
- Mantener costos basados exclusivamente en liquidaciones verificables del ledger durable, agregados en la misma escala temporal.
- Habilitar en la leyenda el toggle individual, el modo `Aislar`/Solo y atenuación contextual al hover, consistente en las tres dimensiones operativas.
- Preservar el resumen superior de Trabajo Actual y retirar la dependencia visual del gráfico actual de los últimos cinco runs puntuales cuando quede sustituida por la nueva autoridad temporal.

## Capabilities

### New Capabilities

- `temporal-multiseries-telemetry`: contrato de series temporales globales y por proyecto para autonomía, tiempo activo y costo, con agregación, ventanas, estados sin datos y metadatos de interacción.

### Modified Capabilities

- `execution-operations-dashboard`: el Dashboard incorpora la nueva visualización temporal multi-serie e interacción de leyenda, conservando la autoridad de costos verificados y el resumen de Trabajo Actual.

## Impact

- Backend de lectura/proyección de Dashboard y servicios de telemetría existentes; no se crea una segunda API ni una autoridad paralela de costos.
- Persistencia y consultas de ejecuciones, eventos de etapas, gates humanos y ledger de costos; cualquier cambio durable deberá usar las migraciones existentes y conservar históricos.
- Frontend Angular del Dashboard, componentes de gráfica, leyenda y estados accesibles para escritorio, tablet y móvil.
- Pruebas unitarias y E2E de navegador acotadas al contrato de telemetría y a la interacción real de la gráfica. El runtime Chromium y los comandos declarados de `frontend` son la vía de verificación del comportamiento UI.
- No incluye despliegue productivo, cambios de scheduler, nuevos proveedores, ni modificaciones del flujo o de la tarjeta de Trabajo Actual fuera de preservar su contrato.
