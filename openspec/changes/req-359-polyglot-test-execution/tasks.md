# Tasks

## 1. Estrategia desacoplada de resolución de pruebas (CandidateTestResolver)

- [x] 1.1 Diseñar e implementar `CandidateTestResolver` (o estrategia equivalente) para inspeccionar el worktree candidato y determinar el arnés de pruebas correspondiente: Node raíz (`package.json`), Node subdirectorio (`frontend/package.json`), Rust (`Cargo.toml`), Go (`go.mod`), o Python (`pyproject.toml`, suites `.py`).
- [x] 1.2 Incorporar la evaluación prioritaria de `project.checks`: si el proyecto define comandos de verificación explícitos, programar su ejecución secuencial antes de la autodetección de arnés.
- [x] 1.3 Implementar diagnóstico de fallo honesto cuando no se identifiquen pruebas o el manifiesto sea desconocido, reportando la tecnología detectada sin atribuir falsamente el fallo a `pytest`.

## 2. Refactorización e integración en el orquestador

- [x] 2.1 Refactorizar `NativeOrchestrationCoordinator._run_automated_tests` para delegar la resolución y ejecución de pruebas en la estrategia desacoplada, preservando el observador de inicio de proceso y el aislamiento de señales PGID.
- [x] 2.2 Preservar la sanitización obligatoria de variables de entorno (purgando `MINIME_DATABASE_URL` y `MINIME_EXPECTED_DATABASE` en los subprocesos de prueba) para prevenir cualquier mutación accidental de la base de datos operacional.
- [x] 2.3 Mantener el registro estructurado de evidencia (`command`, `exit_code`, `duration_ms`, `stdout`, `stderr`) en `active_run.stop_details["test_evidence"]` y el flujo de reintento/fail-closed ante fallos reales.

## 3. Pruebas unitarias y validación E2E

- [x] 3.1 Crear suite de pruebas unitarias (`tests/test_candidate_test_resolver.py`) que verifique:
  - Detección y comando para proyecto Node raíz (`package.json` -> `npm test`).
  - Detección y comando para proyecto Node en subcarpeta (`frontend/package.json` -> `npm --prefix frontend test`).
  - Detección y comando para proyecto Python (selección enfocada con `pytest`).
  - Diagnóstico fiel y fail-closed ante repositorios sin arnés soportado.
  - Priorización de comandos explícitos de `project.checks`.
- [x] 3.2 Ejecutar la suite completa de pruebas unitarias y de regresión de mini me para asegurar 0 regresiones en el monorepo existente.
