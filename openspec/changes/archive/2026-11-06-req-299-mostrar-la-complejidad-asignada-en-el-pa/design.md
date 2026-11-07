# Design

## Context

El componente standalone `frontend/src/app/features/trabajo-actual/trabajo-actual.component.ts` ya selecciona el Run autoritativo mediante `targetRun()` y renderiza el stepper de diez fases. `OrchestrationRun` ya expone `stop_details` como un registro opcional en `frontend/src/app/core/models.ts`, y el endpoint de Runs ya entrega dentro de ese registro los datos de evaluación. La spec delta de este Change modifica únicamente la presentación de ese dato existente.

El frontend tiene pruebas contractuales en `frontend/tests/*.test.mjs` y scripts oficiales `npm test` y `npm run build`. El backend, persistencia, endpoint y evaluación de complejidad quedan fuera del área modificable.

## Goals / Non-Goals

**Goals:**

- Reutilizar `targetRun()` como única fuente del Run seleccionado.
- Presentar nivel `high`, `moderate` o `low`, evidencia opcional y estado «Pendiente» cuando falte el nivel.
- Hacer explícita la consecuencia operativa de `high` usando la información existente de revisiones, sin duplicar la regla de clasificación.
- Mantener una presentación legible y accesible dentro del panel del stepper, con cobertura de contrato y build frontend.

**Non-Goals:**

- No cambiar FastAPI, SQLAlchemy, Alembic, `GET /api/v1/orchestration/runs` ni la escritura de `stop_details`.
- No evaluar, normalizar heurísticamente ni asignar complejidad en el navegador.
- No crear un servicio, estado, endpoint, modelo backend o feature flag nuevo.
- No modificar la selección de Runs, las fases, los gates humanos ni la lógica existente de revisión.

## Decisions

1. **Leer directamente el Run seleccionado.** La plantilla y cualquier helper de presentación consultarán `targetRun()?.stop_details?.complexity` y `targetRun()?.stop_details?.complexity_evidence`. Esto conserva la autoridad existente y evita una segunda lectura o cálculo.
   - Alternativa descartada: pedir un endpoint o campo nuevo al backend; el Issue declara que los datos ya viajan en `stop_details` y exige frontend-only.

2. **Usar un estado de presentación cerrado.** El nivel solo se mostrará como `high`, `moderate` o `low`; cualquier ausencia se muestra como «Pendiente». Un valor desconocido no se convierte en un nivel válido ni en un valor por defecto.
   - Alternativa descartada: tratar `moderate` como fallback; ocultaría que la evaluación aún no existe y violaría la condición de no inventar.

3. **Mantener la implicación de alta complejidad en la UI.** Para `high` se mostrará un texto informativo que indique revisión obligatoria de propuesta y código, sin activar acciones ni inferir que una revisión ya ocurrió. Los datos concretos de revisión seguirán siendo los existentes del Run.
   - Alternativa descartada: recalcular o decidir la política de revisión en Angular; esa autoridad pertenece al pipeline y sus datos persistidos.

4. **Pruebas frontend enfocadas y reales para este contrato.** Se ampliará la suite Node existente para comprobar que el código lee `targetRun()`/`stop_details`, cubre pendiente, los tres niveles, evidencia y la implicación de `high`; se ejecutarán `npm test` y `npm run build` desde `frontend`.
   - Alternativa descartada: modificar backend o usar mocks como evidencia de una integración que este Change no modifica.

## Removal Ledger

| Elemento | Acción | Evidencia esperada |
| --- | --- | --- |
| Stepper y lectura existente de `targetRun()` | RETAIN/MODIFY | El componente continúa siendo el único consumidor; tests contractuales y diff muestran solo la extensión de presentación. |
| `OrchestrationRun.stop_details` | RETAIN | Ya es el contrato frontend existente; no se añade writer ni consumidor alternativo. |
| Evaluación backend y `task_classification_snapshots` | RETAIN-WITH-REASON | Son autoridades de datos fuera del alcance; el frontend solo consume la proyección entregada. |
| Cualquier fallback de complejidad añadido por este Change | REMOVE | No debe existir fallback que invente un nivel; test negativo para ausencia/desconocido. |

No se reemplaza una ruta de ejecución ni una fuente de verdad; por ello no hay código backend, DB o migración que retirar en este Change.

## Risks / Trade-offs

- **[Risk]** `stop_details` puede ser nulo, carecer de la clave o contener un valor futuro. → Encapsular la presentación con acceso opcional y mostrar «Pendiente» sin lanzar errores ni asignar un valor.
- **[Risk]** La evidencia puede ser texto, estructura o estar vacía. → Renderizarla de forma segura como dato disponible, omitirla cuando no exista y no interpretarla como decisión.
- **[Risk]** El texto de `high` puede confundirse con una revisión ya completada. → Usar lenguaje informativo de requisito («requiere revisión») separado de los bloques de resultados existentes.
- **[Risk]** Cambios de plantilla pueden romper el build Angular. → Ejecutar la suite frontend y el build de producción reales como criterios de cierre.

## Migration Plan

No hay migración de datos ni despliegue gestionado por mini me. El cambio se implementa en el frontend, se valida con `npm test` y `npm run build`, y se revierte eliminando la extensión visual si la validación falla; el contrato backend permanece intacto.

## Open Questions

Ninguna: el Issue define los valores válidos, la fuente existente, el estado pendiente y el alcance frontend-only.
