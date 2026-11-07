# Tasks

## 1. Presentación de complejidad

- [x] 1.1 Extender el panel del stepper en `frontend/src/app/features/trabajo-actual/trabajo-actual.component.ts` para leer la complejidad y la evidencia desde `targetRun()?.stop_details`, mostrando `high`, `moderate`, `low` o «Pendiente» sin fallback inventado; verificarlo contra la spec delta y conservar intacta la selección de Runs.
- [x] 1.2 Añadir la indicación visual informativa de que `high` requiere revisión de propuesta y código, separada de cualquier resultado de revisión ya registrado; verificar que no crea acciones, estados ni evaluación nueva en el frontend.
- [x] 1.3 Mantener el contrato frontend existente de `OrchestrationRun.stop_details` y no tocar backend, endpoint, persistencia ni lógica de clasificación; verificar con `git diff --name-only` que el cambio queda limitado a superficies frontend, pruebas y artefactos del Change.

## 2. Pruebas y validación determinista

- [x] 2.1 Ampliar las pruebas frontend existentes para cubrir `high`, `moderate`, `low`, evidencia presente, ausencia de evaluación («Pendiente») y lectura explícita desde `targetRun()?.stop_details?.complexity`; verificar con `npm test` ejecutado desde `frontend` y conservar la salida real.
- [x] 2.2 Ejecutar el build de producción frontend con `npm run build` desde `frontend`; verificar exit code 0 y registrar la salida real como evidencia del candidato.
- [x] 2.3 Validar manualmente en navegador el candidato exacto: (a) Run con `high` muestra complejidad y la obligación de ambas revisiones; (b) Run con `moderate` o `low` muestra el nivel sin esa indicación; (c) Run sin `stop_details.complexity` muestra «Pendiente» y no muestra un nivel; (d) evidencia presente se muestra y ausencia de evidencia no produce texto inventado. Registrar escenarios, SHA base y SHA candidato, viewport y resultado visible; no reutilizar capturas de otro candidato.

## 3. Cierre del alcance

- [x] 3.1 Revisar el diff final y el Removal Ledger del design para confirmar que no se introdujeron consumidores, writers, fallbacks o rutas duplicadas de complejidad; verificar con búsqueda estática y diff que el único origen sigue siendo el Run expuesto por la API.
- [x] 3.2 Ejecutar la validación OpenSpec correspondiente sobre todos los artefactos y conservar el resultado real; no marcar el Change como completo por casillas, tests o auto-reporte si falta evidencia observable de build o validación UI.
