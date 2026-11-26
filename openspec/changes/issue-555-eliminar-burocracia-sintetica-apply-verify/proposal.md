## Why

Apply/Verify todavía rechaza candidatos por texto estático sobre publicación, puede tratar cachés de compilación como suciedad del worktree y depende de la caché doméstica para localizar Playwright. Además, la guía de autoría puede clasificar como bloqueante una integración que ya tiene un respaldo local suficiente. Estas comprobaciones agregan fricción sin mejorar la evidencia del árbol Git y de las pruebas ejecutadas.

## What Changes

- Eliminar el detector regex y la validación textual de claims de publicación al evaluar tareas; las menciones de servicios no invalidan un candidato.
- Excluir cachés de compilación conocidas mediante el `.git/info/exclude` compartido del clon, que Git aplica a sus worktrees, y hacer que el Commit Guardian respete esas exclusiones.
- Fijar `PLAYWRIGHT_BROWSERS_PATH=/opt/minime/runtime/playwright-browsers` en el entorno aislado de verificación, sin depender de cachés de usuario ni descargas.
- Aclarar en la autoría de Changes que un respaldo local funcional suficiente puede satisfacer una contingencia; la evidencia lo registra como `fallback_applied` y `blocking: false`.

## Capabilities

### New Capabilities

Ninguna.

### Modified Capabilities

- `openspec-task-tracking`: la validación de tareas no rechaza menciones textuales de publicación; conserva los criterios generales de evidencia del contrato rector.
- `worktree-lifecycle`: el worktree recibe exclusiones locales de cachés y los controles de Git respetan su efecto.
- `deterministic-checks-runner`: el entorno aislado de Playwright resuelve navegadores desde la ruta runtime canónica.
- `openspec-native-propose`: la evaluación de contingencias acepta y verifica respaldos funcionales suficientes sin marcar bloqueo.

## Impact

- Código probable: `src/minime/services/orchestration_coordinator.py`, `src/minime/services/worktree_manager.py` y el preparador de entorno de pruebas/Playwright.
- Tests pertinentes: `tests/test_f3_fail_closed_contracts.py`, pruebas de ciclo de vida/Commit Guardian del worktree, `tests/test_candidate_test_resolver.py` y pruebas focalizadas de preparación/evaluación de propuesta.
- Skills de autoría y `openspec/specs/` para documentar contingencias; no se añaden dependencias, tablas ni estados operativos.
- La verificación de integraciones que un criterio realmente exige sigue necesitando evidencia observable según el contrato rector; esta propuesta retira la interpretación de texto estático como evidencia de despliegue.
