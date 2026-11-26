# Proposal

## Why

Los Human Gates ya llegan a `Trabajo actual` desde la autoridad durable y conservan el flujo de respuesta, pero su contenido puede aparecer como texto técnico concatenado y difícil de accionar. Esto aumenta el riesgo de que el operador no entienda por qué el run está detenido, qué decisión debe tomar o qué efecto tendrá cada opción, especialmente en `proposal_feasibility` y `apply_escalation`.

El cambio mejora la legibilidad sin relajar los gates humanos, cambiar transiciones ni ocultar la auditoría: el resumen y las decisiones serán claros en español, mientras que los datos de bajo nivel quedarán disponibles bajo demanda.

## What Changes

- Enriquecer `stop_details["human_payload"]` para los gates de `proposal_feasibility` y `apply_escalation` con `summary_es`, `pending_items` y `options_es`, manteniendo la pregunta y las opciones originales necesarias para la autoridad del workflow.
- Presentar en `frontend/src/app/features/trabajo-actual/` una cabecera ejecutiva de dos líneas, bloqueos/advertencias como viñetas tituladas y opciones orientadas a la acción en español llano.
- Mover hashes, payloads crudos, diffs y demás diagnóstico técnico a un acordeón `Detalles técnicos y auditoría`, sin perder la identidad ni el contexto del gate.
- Añadir degradación compatible para payloads históricos: limpiar separadores de punto y coma, mostrar opciones heredadas de forma legible y no fallar si faltan los campos enriquecidos.
- Conservar intactos el endpoint, el envío de respuestas, la autoridad de transición, la seguridad fail-closed y la presentación de una pregunta vigente con sus opciones originales.
- Retirar únicamente la ruta visual monolítica que quede sustituida dentro del componente de Human Gates, una vez cubierta por la nueva presentación y sus pruebas; conservar los datos históricos y la auditoría.

## Capabilities

### New Capabilities

<!-- None: the behavior extends the existing Trabajo actual/Human Gate contract. -->

### Modified Capabilities

- `pwa-runs-and-pipeline-observability`: refine the Human Gate payload and its `Trabajo actual` presentation while preserving durable gate authority, original workflow options, response submission, and state transitions.

## Impact

- Backend: `NativeOrchestrationCoordinator` and the existing Runs projection/endpoints that construct or expose `stop_details["human_payload"]`; no new persistence model or state transition.
- Frontend: `frontend/src/app/features/trabajo-actual/trabajo-actual.component.ts`, its existing models/helpers and focused unit tests; no route or response API replacement.
- Verification: focused backend/frontend unit coverage, a real-browser Playwright scenario for the structured gate, and evidence that the existing response endpoint and durable transition path remain unchanged.
- No new dependency, provider, deployment, paid service, or change outside this vertical slice is introduced.
