## 1. Retirar rechazo textual de publicación

- [x] 1.1 Eliminar `_PUBLISHED_CANDIDATE_CLAIM` y su rama de rechazo en la evaluación de tareas; censar y retirar helpers/markers que queden sin consumidores, conservando cualquier evidencia requerida por un criterio real de integración. Evidencia: búsqueda de consumidores confirma que se conserva `_PUBLISHED_EVIDENCE_MARKER` y su validación SHA porque el flujo real de candidato la usa; se retiró únicamente el regex textual.
- [x] 1.2 Actualizar o sustituir las pruebas de rechazo estático para demostrar que menciones a GitHub Pages/Pages.dev no invalidan una tarea con evidencia de árbol y tests, y que la mención no cuenta como evidencia de integración. Verificado desde este worktree con `PYTHONPATH=src python -m pytest tests/test_f3_fail_closed_contracts.py -k 'published_version_evidence or publication_wording'`: 2 passed.

## 2. Excluir cachés en el worktree

- [x] 2.1 Añadir idempotentemente los patrones `**/.angular/cache/`, `**/.turbo/`, `**/.next/cache/` y `**/node_modules/.cache/` al archivo efectivo devuelto por `git rev-parse --git-path info/exclude`; Git comparte ese archivo entre los worktrees del clon. Mantener intacto el `.gitignore` del proyecto.
- [x] 2.2 Añadir una prueba Git real de worktree que compruebe que las cuatro cachés quedan ignoradas y que un archivo no relacionado sigue visible para el Commit Guardian. Verificado con `PYTHONPATH=src python -m pytest tests/test_worktree_and_runner.py -k 'worktree_manager_create_collision_and_cleanup'`: 1 passed.

## 3. Usar la instalación runtime de Playwright

- [x] 3.1 Configurar `PLAYWRIGHT_BROWSERS_PATH=/opt/minime/runtime/playwright-browsers` en el entorno aislado empleado por detección y ejecución de checks Playwright; eliminar la dependencia de cachés domésticas y no agregar descargas/fallbacks. Evidencia: la configuración inyecta la ruta constante y el resolver solo inspecciona esa instalación.
- [x] 3.2 Probar resolución desde la ruta runtime y fallo explícito sin descarga ni caché de usuario cuando no haya navegador. Verificado con `PYTHONPATH=src python -m pytest tests/test_candidate_test_resolver.py -k 'playwright or browser'`: 3 passed; E2E real `test_declared_playwright_runs_against_served_candidate_and_binds_sha`: 1 passed usando el navegador preinstalado como fixture temporal (la ruta canónica `/opt/minime/runtime/playwright-browsers` no existe en este Mac); el escenario de runtime ausente falló como esperado, sin fallback.

## 4. Admitir contingencia local con evidencia

- [x] 4.1 Extender el reporte y validador existente de `ProposalFeasibilityEvaluator` con estado de contingencia, indicador de bloqueo, explicación y referencias; aceptar `fallback_applied` con `blocking: false` solo si la ruta local existe y hay verificación funcional mapeada, manteniendo bloqueado el respaldo insuficiente.
- [x] 4.2 Actualizar `minime-openspec-change-author` para que el agente describa contingencias suficientes y su verificación en OpenSpec; añadir pruebas del validador para contingencia suficiente, ausente y no funcional. Verificado con `PYTHONPATH=src python -m pytest tests/test_proposal_feasibility_safe_paths.py tests/test_proposal_feasibility_operator_override.py`: 7 passed.

## 5. Verificación focalizada del Change

- [x] 5.1 Ejecutar las verificaciones focalizadas y validar los artefactos. Evidencia: `PYTHONPATH=src python -m pytest -q tests/test_worktree_and_runner.py tests/test_candidate_test_resolver.py tests/test_proposal_feasibility_safe_paths.py tests/test_proposal_feasibility_operator_override.py tests/test_candidate_playwright_e2e.py` (39 passed, 1 skipped porque el navegador runtime canónico no está instalado en este Mac); E2E Playwright real con navegador preinstalado como fixture temporal (1 passed; registrado en 3.2); `PYTHONPATH=src python -m pytest -q tests/test_f3_fail_closed_contracts.py -k 'published_version_evidence or publication_wording'` (2 passed); `python -m ruff check --output-format concise` sobre los archivos Python cambiados (All checks passed); `openspec validate issue-555-eliminar-burocracia-sintetica-apply-verify --strict --no-interactive` (valid). SHA inmutable del candidato: se establecerá al registrar este Apply en el commit local dedicado.
