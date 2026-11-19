# Proposal

## Why

Mini me está concebido para orquestar proyectos de software en cualquier plataforma o tecnología (Web, Python, Go, Rust, Node, etc.). Sin embargo, la verificación automatizada en `NativeOrchestrationCoordinator._run_automated_tests` actualmente asume de forma rígida que todo proyecto o es Python (buscando suites para ejecutar con `pytest`) o tiene su frontend confinado en la subcarpeta `frontend/` de mini me.

Al orquestar un proyecto real externo como Múltiplo (web pura en JavaScript con `package.json` en la raíz), el orquestador reportó falsamente `Test selection failed: no tests were selected; pytest was not run` y pausó la corrida, a pesar de que la suite nativa del candidato (`npm test`) pasó al 100% con 17 tests válidos. Este cambio desacopla el motor de pruebas a una estrategia políglota nativa que honra la tecnología del repositorio y los `project.checks` configurados, erradicando el sesgo de monorepo interno.

## What Changes

- **Estrategia desacoplada de selección y ejecución de pruebas (Strategy Pattern):**
  - **Prioridad 1 (Configuración explícita):** Si el proyecto tiene configurados comandos en `project.checks`, ejecutar dichos comandos antes de aplicar la autodetección genérica.
  - **Prioridad 2 (Arnés nativo Node / JavaScript / TypeScript):**
    - Si existe `package.json` en la raíz del worktree: ejecutar `npm test` en el directorio raíz.
    - Si existe `package.json` en `frontend/` y los cambios se circunscriben a esa subcarpeta: ejecutar `npm --prefix frontend test`.
  - **Prioridad 3 (Arnés nativo Rust):**
    - Si existe `Cargo.toml`: ejecutar `cargo test`.
  - **Prioridad 4 (Arnés nativo Go):**
    - Si existe `go.mod`: ejecutar `go test ./...`.
  - **Prioridad 5 (Arnés nativo Python):**
    - Si existen manifiestos Python (`pyproject.toml`, `pytest.ini`, `setup.py`) o archivos de prueba `.py`: aplicar la selección de tests enfocados y ejecutar con `pytest`.
- **Diagnósticos y evidencia honestos:**
  - Si un proyecto no declara pruebas o no se reconoce un arnés soportado, reportar un diagnóstico exacto a la tecnología encontrada (ej. *"No test script defined in package.json"* o *"No supported test harness detected in repository"*), jamás reportando que `pytest` no corrió en proyectos ajenos a Python.
- **Preservación inmutable de evidencia:**
  - Mantener la captura estructurada de `command`, `exit_code`, `duration_ms`, `stdout` y `stderr` persistidos en PostgreSQL como evidencia de verificación real E2E.

## Capabilities

### New Capabilities
- Ninguna.

### Modified Capabilities
- `openspec-native-apply-and-verify`: Incorporar el soporte explícito para arneses de pruebas políglotas (Node, Go, Rust, Python) y respeto prioritario a `project.checks` durante el gate de pruebas automatizadas de Apply/Verify.

## Impact

- **Código modificado:**
  - `src/minime/services/orchestration_coordinator.py`: Refactorización de `_run_automated_tests` y métodos auxiliares de selección a una estrategia desacoplada.
- **APIs y modelos:**
  - No altera los esquemas de base de datos ni contratos de la API REST; reutiliza `active_run.stop_details["test_evidence"]` y `project.checks`.
- **Compatibilidad:**
  - Totalmente retrocompatible con el monorepo de mini-me (Python backend + `frontend/` Angular), habilitando inmediatamente a proyectos brownfield de Node/Web (como Múltiplo), Rust y Go.
