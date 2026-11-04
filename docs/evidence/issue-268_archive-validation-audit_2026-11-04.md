# Issue #268 — auditoría de `openspec validate --archived`

**Rama:** `chore/archive-validate-cleanup-268`
**Base auditada:** `origin/main` en `95cff5f75cd5e4c51f7dcc0b0f73f57655016da1` (incluye el merge documental #277).
**Regla:** una tarea se marca `[x]` solo con respaldo en diff/código, pruebas o un PR/historial identificable que cubra el criterio. Un resumen de implementación no acredita gates externos que el mismo expediente deja pendientes.

## Resultado inicial

`openspec validate --archived --json` examinó 65 changes: **55 válidos, 10 inválidos**. Las diez fallas eran `tasks.md` con tareas sin marcar; el validador no informó artefactos faltantes:

| Change archivado | Falla inicial |
| --- | --- |
| `2026-08-30-011-preserved-candidate-remediation-generations` | 83 tareas incompletas (0/83) |
| `2026-09-02-018.2-autonomous-end-to-end-execution` | 2 (6/8) |
| `2026-09-03-018.2-proving-diagnostic-status` | 3 (0/3) |
| `2026-09-04-020-operator-experience-parity-and-production-console-reliability` | 16 (0/16) |
| `2026-10-07-scheduler-and-recovery-convergence` | 3 (79/82) |
| `2026-10-09-local-worker-capability-routing-policy` | 25 (0/25) |
| `2026-10-25-gacela-04-skills-base` | 3 (31/34) |
| `2026-10-29-gacela-05-ui-self-hosted` | 7 (28/35) |
| `2026-11-03-doc-closing-idempotency` | 1 (4/5) |
| `req-211-f12-depuracion-real-y-erradicacion-defin` | 23 (0/23) |

## Reconciliación por Change

### `2026-08-30-011-preserved-candidate-remediation-generations`

Se marcaron 75 tareas con evidencia de PR #34 (head `be25330935d84542d303d731d645bbc9530ea9b0`, merge `0aa24f1463197881389ed244a8d186a271ac08c1`): modelo/servicio/repositorio/migración en el diff; suites `test_candidate_remediation.py`, `test_candidate_remediation_persistence.py` y `test_candidate_remediation_real_git.py`; PR informa 393 pruebas aprobadas, Ruff y OpenSpec strict; una sola cabeza Alembic; revisión complementaria y auditoría independiente aprobadas. Los tests históricos de Git incluyen replay sin doble invocación, source SHA/base preservados, scope violation, fallo de N+1 y lineage N+2. El test `test_candidate_remediation_real_git.py` fue retirado después por `cd14d1d` durante otro cambio, así que se usa el diff y resultado del PR original, no se afirma que el archivo exista hoy.

Quedan `[ ]`: **2.5, 12.7, 13.2, 13.3, 13.4, 13.6, 13.7, 13.9**. PR #34 no conserva salida de `alembic upgrade head --sql` (2.5); el test de base avanzada encontrado es persistencia/unitario, no la E2E real solicitada (12.7); no se identificó evidencia individual para las suites de human-resolution, adopción legacy ni transition-key (13.2–13.4); no se acredita que las 393 pruebas se ejecutaran con variables DB unset, ni aceptación de migración PostgreSQL desechable, ni `git diff --check` (13.6, 13.7, 13.9).

### `2026-09-02-018.2-autonomous-end-to-end-execution`

Se mantienen `[ ]` **7 y 8**. PR #52 (`336fece`) informa 566 pruebas y Ruff; no aporta una revisión complementaria/DeepSeek identificada ni resultado observable del bounded proving run requerido.

### `2026-09-03-018.2-proving-diagnostic-status`

Se marcaron 1–3 a partir de PR #54, merge `6aca2a84203a56c4e5ad9d08333a8544d5f360df`, que añade `StatusService.get_pipeline_diagnostic`, tests en `tests/test_status_observability.py` y su validación. Ya no falla en la segunda corrida.

### `2026-09-04-020-operator-experience-parity-and-production-console-reliability`

Se marcaron 1.1 y 1.2: `discover_and_load_env_file()` existe en `src/minime/config.py` y se invoca desde `load_config()` y el inicio de `src/minime/cli/main.py`. Queda `[ ]` **1.3** porque los tests encontrados prueban archivo explícito y preservación de variables, pero no cubren el criterio completo de autodiscovery/error handling. También quedan `[ ]` **2.1–2.6, 3.1–3.2 y 4.1–4.5**: PR #60 entrega otra unidad (intake/onboarding/backlog) y no acredita estos controles de consola ni los cambios/validaciones sobre el host de producción descritos en estas tareas.

### `2026-10-07-scheduler-and-recovery-convergence`

Se mantienen `[ ]` **11.2, 11.3 y 11.7**. PR #103 registra pruebas y afirma que `minime-scheduler.service` sigue deshabilitado, pero no se encontró registro de revisión independiente contra SHA inmutable para 11.2–11.3 ni captura verificable del estado `systemctl` para 11.7. El texto del PR por sí solo no prueba ese estado externo.

### `2026-10-09-local-worker-capability-routing-policy`

Se marcaron 24 tareas (1.1–1.10, 2.1–2.9, 3.1–3.3 y 4.1–4.2) con el diff de PR #123 (`d7c6459`), módulos `models.py`, `evidence_authority.py`, `capability_router.py`, `service.py`, suites de router/integración y la evidencia declarada en PR: 29 pruebas focalizadas y 119 de la suite local, OpenSpec strict aprobado. Queda `[ ]` **4.3**: el PR declara “scheduler inactive + enabled”, sin evidencia externa que pruebe ausencia de reinicio o mutación del repositorio administrado.

### `2026-10-25-gacela-04-skills-base`

Se mantienen `[ ]` **6.2, 6.5 y 6.6**. PR #187 declara expresamente Verify 31/34 y deja esas tres tareas pendientes; no se usó el merge del PR documental como sustituto de esos gates.

### `2026-10-29-gacela-05-ui-self-hosted`

Se marcó **8.3** usando PR #199: registra Sync/Archive nativos, rama documental fresca basada en `main` y el PR2 documental fusionado. Quedan `[ ]` **7.2, 7.3, 7.4, 8.1, 8.2 y 8.4**. PR #198 dice expresamente que la autoejecución F5 y gates posteriores no se presentan como completados; PR #199 solo prueba el cierre documental, no los E2E de navegador/HUMAN_REQUIRED, validación humana/revisión independiente, trazas reales de agentes, ni el ciclo completo de autorización/merge/liberación durable solicitado por esos IDs.

### `2026-11-03-doc-closing-idempotency`

Se mantiene `[ ]` **2.2**. PR #276 difirió explícitamente la E2E contra fixture GitHub real; la prueba de coordinator usa dobles. PR #277 archiva el Change, pero no convierte esa E2E en evidencia.

### `req-211-f12-depuracion-real-y-erradicacion-defin`

Se marcaron **2.1, 2.2, 2.4, 2.5, 2.6 y 3.4** con el diff de PR #251 (`d12f981`, merge `d525a36`): elimina `src/minime/tui/`, comandos CLI identificados, rutas 410, `legacy_unavailable`, dependencia `textual` y tests obsoletos. El ledger de `design.md` y el body de PR #251 delimitan esas retiradas; PR informa 981 pruebas aprobadas.

Quedan `[ ]`: **1.1–1.5, 2.3, 3.1–3.3, 4.1–4.6 y 5.1–5.2**. El diff/PR no aporta candidato/base y baseline íntegros, traza dinámica separada, prueba del build Angular tras retirar assets, retirada de emulación OpenSpec, justificación de modelos/DB y migraciones, evidencia de journeys API/browser/E2E ni aplicación/verificación nativa del Change y sus límites de ejecución. La suite de 981 pruebas no acredita por sí sola esos criterios específicos.

## Resultado después de reconciliar

La segunda corrida de `openspec validate --archived` examinó 65 changes: **56 válidos, 9 inválidos**. La entrada de diagnóstico `2026-09-03-018.2-proving-diagnostic-status` quedó resuelta. Las nueve entradas que aún fallan son:

| Change archivado | Estado tras reconciliar |
| --- | --- |
| `2026-08-30-011-preserved-candidate-remediation-generations` | 8 tareas sin respaldo (75/83) |
| `2026-09-02-018.2-autonomous-end-to-end-execution` | 2 (6/8) |
| `2026-09-04-020-operator-experience-parity-and-production-console-reliability` | 14 (2/16) |
| `2026-10-07-scheduler-and-recovery-convergence` | 3 (79/82) |
| `2026-10-09-local-worker-capability-routing-policy` | 1 (24/25) |
| `2026-10-25-gacela-04-skills-base` | 3 (31/34) |
| `2026-10-29-gacela-05-ui-self-hosted` | 6 (29/35) |
| `2026-11-03-doc-closing-idempotency` | 1 (4/5) |
| `req-211-f12-depuracion-real-y-erradicacion-defin` | 17 (6/23) |

Las tareas con respaldo se marcaron en los `tasks.md` archivados. Todas las casillas restantes conservan `[ ]`; sus IDs y brechas están anotados tanto aquí como al pie del `tasks.md` correspondiente. Cada falla restante refleja evidencia ausente, no una casilla mantenida abierta por error ni una casilla marcada para silenciar el validador.
