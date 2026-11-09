# Technical Design

## Context

El orquestador de mini me (`NativeOrchestrationCoordinator`) ejecuta pruebas automatizadas en la etapa `RUNNING_TESTS` posterior al Apply nativo de OpenSpec. El método `_run_automated_tests` delega actualmente en `_select_relevant_test_paths`, el cual busca únicamente archivos `.py` (`test_*.py` / `*_test.py`). Si no encuentra archivos Python, solo contempla una excepción cableada para cambios confinados en `frontend/`.

Para que mini me actúe como un orquestador agnóstico y políglota, la resolución y ejecución de pruebas debe desacoplarse en una estrategia de ejecución basada en el manifiesto tecnológico del candidato y en la configuración explícita del proyecto (`project.checks`).

Ver motivación completa en `proposal.md` y especificación de comportamiento en `specs/openspec-native-apply-and-verify/spec.md`.

## Goals / Non-Goals

**Goals:**
- Desacoplar la selección y ejecución de pruebas mediante una abstracción limpia (`CandidateTestResolver` / `CandidateTestStrategy`).
- Priorizar la ejecución de `project.checks` si el proyecto tiene declarados comandos de verificación explícitos.
- Autodetectar y ejecutar el arnés nativo de pruebas según los manifiestos del candidato:
  - Node raíz (`package.json` en `worktree_path`): `npm test`.
  - Node en subcarpeta monorepo (`frontend/package.json`): `npm --prefix frontend test`.
  - Rust (`Cargo.toml`): `cargo test`.
  - Go (`go.mod`): `go test ./...`.
  - Python (`pyproject.toml`, `pytest.ini` o suites `.py`): selección enfocada de pruebas con `pytest`.
- Preservar la observabilidad completa: capturar `command`, `exit_code`, `duration_ms`, `stdout` y `stderr` como evidencia inmutable.
- Proveer diagnósticos fidedignos sin atribuir falsamente fallos a `pytest` en proyectos sin tecnología Python.

**Non-Goals:**
- No reemplazar los pipelines de CI/CD completos del proyecto; mini me ejecuta el gate enfocado del cambio antes de la revisión independiente y el PR.
- No alterar el esquema de base de datos de PostgreSQL ni requerir migraciones de Alembic (reutiliza `active_run.stop_details["test_evidence"]` y `project.checks`).

## Decisions

### 1. Desacoplamiento de la Estrategia de Pruebas (Strategy Pattern)
- **Decisión:** Extraer la lógica de detección y ejecución de pruebas fuera del flujo monolítico de `NativeOrchestrationCoordinator` hacia una clase dedicada `CandidateTestResolver` (o métodos especializados cohesivos).
- **Razón:** Cumple con el principio de responsabilidad única (SRP) y facilita pruebas unitarias aisladas sin necesidad de levantar el ciclo completo de orquestación.
- **Alternativa descartada:** Seguir agregando cláusulas `elif` anidadas dentro de `_run_automated_tests`. Dificulta el mantenimiento y perpetúa el código espagueti.

### 2. Orden de Prevalencia de Resolución
- **Decisión:** El orden de resolución para ejecutar el gate de pruebas será:
  1. **Comandos configurados en `project.checks`**: Si el proyecto tiene configurados comandos de verificación, se ejecutan de forma secuencial.
  2. **Manifiesto Node raíz (`package.json`)**: Si existe en la raíz del worktree, se invoca `npm test`.
  3. **Manifiesto Node subcarpeta (`frontend/package.json`)**: Si los cambios son de frontend en monorepo, se invoca `npm --prefix frontend test`.
  4. **Manifiesto Rust (`Cargo.toml`)**: Invocar `cargo test`.
  5. **Manifiesto Go (`go.mod`)**: Invocar `go test ./...`.
  6. **Arnés Python (`pytest`)**: Si se detectan suites Python o manifiestos (`pyproject.toml`, etc.), ejecutar selección enfocada.
- **Razón:** Respeta la configuración explícita del operador por encima de la autodetección, y dentro de la autodetección respeta el manifiesto tecnológico real del repositorio.

### 3. Preservación del Sandbox y Sanitización de Entorno
- **Decisión:** Mantener la purga de variables de base de datos operacional (`MINIME_DATABASE_URL`, `MINIME_EXPECTED_DATABASE`) en cualquier subproceso de pruebas ejecutado, garantizando que ninguna prueba de ningún lenguaje pueda mutar la base de datos de producción.

## Risks / Trade-offs

- **[Riesgo]** Un proyecto Node puede tener `package.json` pero carecer de script `"test"` en `scripts`.
  - **Mitigación:** Si `npm test` falla porque no existe script de test (error común: `Missing script: "test"`), capturar el error claramente y reportar diagnóstico específico, sin colapsar el orquestador.
- **[Riesgo]** Tiempos de ejecución prolongados en suites completas.
  - **Mitigación:** Mantener el observador de inicio de proceso (`process_start_observer`), el rastreo de PGID y los timeouts duros ya existentes en el orquestador para prevenir procesos zombi.
