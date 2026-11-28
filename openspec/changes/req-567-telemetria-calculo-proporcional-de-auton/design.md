# Design

## Context

La capacidad existente ya concentra la lectura temporal en `TemporalMultiseriesTelemetryService`, alimentada por runs, eventos de etapas, acciones/gates y liquidaciones, y el Dashboard consume ese DTO. La ruta actual clasifica el Run como `no_intervention`, `autonomous_recovery` u `operator_needed` y proyecta 100/0; las pruebas enfocadas y la E2E del Dashboard ya cubren la forma de la proyección, los outcomes y la preservación de Trabajo Actual. Este Change modifica esa autoridad de lectura y añade la capacidad de reproyección histórica definida en las specs, manteniendo la pureza de las consultas y PostgreSQL como dueño de la evidencia.

## Goals / Non-Goals

**Goals:**

- Derivar una proporción por etapas recorridas: etapas autónomas / etapas elegibles recorridas, con reglas explícitas para gobernanza, recuperación autónoma, bloqueo técnico y acción del operador.
- Mantener la clasificación fail-closed ante evidencia incompleta o contradictoria y conservar no-data.
- Reutilizar el endpoint y el DTO de telemetría existentes, agregando solo los campos de explicación que sean necesarios para hacer observable el cálculo.
- Recalcular históricos en tiempo de proyección desde PostgreSQL, de forma idempotente y sin reescribir hechos durables.
- Retirar el camino binario y actualizar sus consumidores y pruebas después de demostrar paridad del nuevo cálculo.

**Non-Goals:**

- No crear una cola, scheduler, tabla de backlog, servicio paralelo de telemetría ni motor genérico de scoring.
- No cambiar la autoridad de runs, gates, acciones, eventos, liquidaciones o la navegación de Trabajo Actual.
- No inventar una ponderación alternativa: el contrato de este Change adopta la proporción simple por etapas recorridas.
- No borrar, compactar ni migrar destructivamente históricos; no desplegar producción.

## Decisions

### 1. Proporción simple por etapas recorridas

El servicio calculará cada observación de autonomía a partir de las etapas con evidencia completa del Run. El numerador será el número de etapas autónomas; el denominador será el total de etapas recorridas y clasificables. Una autorización de gobernanza se expone como outcome separado y permanece en el denominador como etapa no autónoma, lo que produce 5/6 (83.33%) en el caso del Issue. Se descarta un ratio ponderado de control de máquina porque requeriría pesos nuevos no presentes en la evidencia y haría menos explicable la métrica.

### 2. Clasificación separada, agregación proporcional

Se conservarán categorías de evidencia (`no_intervention`, `autonomous_recovery`, `governance_authorization`, `technical_block`, `operator_needed`, `unverified`) a nivel de etapa/outcome. La agregación temporal usará las proporciones de los Runs elegibles y sumará los outcomes sin convertir de nuevo el Run a 0/100. La representación existente de `autonomy_outcomes` se ampliará de forma compatible o se reemplazará por un mapa explícito de conteos si el contrato actual no puede expresar gobernanza y bloqueo sin ambigüedad.

### 3. Reproyección de lectura, no backfill destructivo

La proyección histórica recalculará desde los repositorios existentes cada vez que se solicite el Dashboard o la ruta de telemetría. No se añadirá una tabla de snapshots ni se mutarán runs para almacenar el resultado derivado; así la actualización es inmediata, idempotente y no necesita migración. Si el inventario durante Apply demuestra que existe un writer histórico separado que impide la lectura completa, deberá modificarse dentro de este Change mediante migración Alembic conservadora, preservando los hechos y sin duplicar la autoridad.

### 4. Pureza de consultas y compatibilidad del Dashboard

Se conservará el GET de Dashboard como read model sin commits, eventos, locks de escritura ni reparación automática, conforme a `projection-purity-and-cqs`. El frontend continuará leyendo las tres dimensiones y solo adaptará el renderizado del resumen de autonomía a los nuevos outcomes/campos. Trabajo Actual seguirá usando su fuente autoritativa independiente.

### 5. Retirada segura del comportamiento sustituido

Removal Ledger del Change:

| Replaced behavior | Old entrypoints/writers | Reachability / action | Migration owner | New authority / evidence |
|---|---|---|---|---|
| Autonomía binaria por Run (`operator_needed` ⇒ 0) | `_observation`/`_autonomy_outcome` y aserciones 0/100 de `tests/test_temporal_multiseries_telemetry.py` | Censar callers del DTO; MIGRATE al cálculo por etapas y REMOVE solo el branch binario sin consumidores | Runs, eventos, gates, acciones y migraciones existentes se RETAIN | Servicio temporal actual con pruebas unitarias y E2E real de 5/6, recuperación y bloqueo |
| Reproyección que dependiera de datos precalculados | Cualquier writer/read-model encontrado durante Apply | Verificar con `rg`, repositorios y trazas; REMOVE duplicados o RETAIN-WITH-REASON si tienen consumidor durable | PostgreSQL/Alembic y audit evidence se RETAIN | Lectura idempotente de todos los runs históricos, con estado antes/después idéntico |

No se retirarán eventos, audit trails, migraciones aplicadas, runs ni worktrees. La evidencia final deberá demostrar no callers del camino binario, tests green después de su eliminación y ausencia de mutaciones transitorias durante la reproyección.

## Risks / Trade-offs

- [Riesgo] Runs históricos pueden no contener eventos suficientes para reconstruir etapas. → Mitigación: excluirlos como `unverified`, informar el conteo y no fabricar porcentajes.
- [Riesgo] Cambiar el shape de outcomes puede romper el frontend o consumidores externos. → Mitigación: inventariar callers, mantener compatibilidad estructural cuando sea posible y cubrir API + navegador real antes de retirar campos.
- [Riesgo] Promediar proporciones de Runs da el mismo peso a Changes de distinta cantidad de etapas. → Mitigación: documentar y probar la unidad de agregación; no introducir ponderación no autorizada por el Issue.
- [Riesgo] Una acción de operador asociada a una autorización puede no identificar su tipo. → Mitigación: exigir evidencia de categoría; si es ambigua, clasificar como `unverified` y fail-closed.
- [Riesgo] Una consulta histórica grande puede aumentar latencia. → Mitigación: conservar ventana acotada y repositorios existentes, medir la consulta con datos reales y optimizar solo índices/consultas necesarios, sin introducir cache mutable que se convierta en otra fuente de verdad.

## Migration Plan

1. Inventariar el servicio, repositorios, endpoint, DTO, frontend, fixtures, E2E y writers; capturar el estado inicial y confirmar que el GET es puro.
2. Implementar el cálculo proporcional y la clasificación separada, con pruebas de contrato de governance-only, bloqueo técnico, recuperación, evidencia ambigua y no-data.
3. Adaptar el payload y el Dashboard si el nuevo detalle no puede expresarse con el shape actual; ejecutar la E2E real del Dashboard con Chromium configurado.
4. Eliminar la ruta binaria sustituida y repetir la suite acotada, la E2E y la comprobación de pureza después del retiro.
5. Verificar la reproyección contra un conjunto PostgreSQL con históricos multi-proyecto, comparar estado durable antes/después y registrar el SHA, respuesta y efectos observables.

Rollback: revertir el candidato antes del merge mediante Git/PR conservando PostgreSQL sin cambios, ya que la estrategia no muta datos históricos ni exige una migración destructiva. Si Apply descubre una incompatibilidad de contrato que requiera cambiar las specs, detenerse y usar el workflow nativo `openspec update`.
