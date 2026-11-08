# Proposal

## Why

La tarjeta «Trabajo actual» dedica su espacio visual principal al botón «Volver a Trabajo», cuyo texto puede partirse, y no ayuda a reconocer rápidamente la etapa observada. El Issue #301 solicita reorganizar esa tarjeta y usar el espacio liberado para mostrar la ilustración normativa de la etapa del run seleccionado, manteniendo la supervisión textual y la navegación existentes.

## What Changes

- Reorganizar el encabezado de la tarjeta para colocar «Volver a Trabajo» debajo de «Supervisión detallada…» y conservar el texto del botón en una sola línea.
- Mostrar una ilustración decorativa para cada etapa admitida: ADMITTED, EXPLORING, PROPOSING, PROPOSAL_REVIEW, IMPLEMENTING, RUNNING_TESTS, VERIFYING, CODE_REVIEW, PREPARING_PR y COMPLETED.
- Incorporar exactamente los diez archivos PNG asignados por la tabla normativa del Issue, con un mapeo explícito por nombre de etapa; no inferir asignaciones por orden de archivos.
- Mantener la tarjeta funcional cuando no exista run seleccionado o la etapa sea desconocida, sin cambiar navegación, semántica de estados ni contenido textual de supervisión.
- Ajustar tamaño, alineación y responsive layout de la ilustración para que la tarjeta rediseñada no supere la altura actual con el mismo viewport y contenido.

## Capabilities

### New Capabilities

### Modified Capabilities

- `pwa-responsive-and-offline-pwa`: la vista PWA de Trabajo actual debe conservar reflow, accesibilidad y operación en los tamaños admitidos mientras reorganiza su tarjeta principal y presenta una ilustración decorativa dependiente de la etapa.

## Impact

- `frontend/src/app/features/trabajo-actual/trabajo-actual.component.ts`: plantilla, estilos de layout y resolución explícita de ilustración por etapa.
- `frontend/public/` (o el directorio de assets público que confirme la configuración Angular): diez PNG aprobados por el Issue.
- Pruebas frontend focalizadas y una validación de navegador real de la tarjeta en desktop, tablet y móvil; el build Angular debe seguir produciendo el shell.
- Sin cambios de API, modelos de run, persistencia, navegación, service worker, estados del workflow, despliegue ni datos autenticados.
