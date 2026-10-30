# Tasks

## 1. Censo y límites de F6

- [x] 1.1 Ejecutar el workflow nativo de apply en el worktree autorizado y registrar Issue #174, Change, repositorio, base SHA, proveedor/skill y permisos; verificar que la identidad de candidato y el worktree coinciden con el binding durable.
- [x] 1.2 Inventariar código, callers, writers, rutas API/CLI/UI, flags, dependencias, tests, fixtures, documentación, migraciones, tablas/columnas, worktrees, jobs/claims, presupuestos y referencias del fixture; entregar el Removal Ledger clasificado REUSE/MODIFY/REMOVE/RETAIN-WITH-REASON y verificar cobertura estática/configuración.
- [x] 1.3 Confirmar el orden F1→F6, el cierre aplicable de F5 y la ausencia de dependencias activas de F2–F5, pruebas o cierres sobre la limpieza propuesta; verificar que F7/F8 y el despliegue no aparecen como trabajo ejecutable.

## 2. Línea base y autoridad retenida

- [x] 2.1 Identificar la nueva autoridad de cada comportamiento candidato y ejecutar las pruebas enfocadas, regresiones y E2E reales de las rutas retenidas antes del retiro; verificar resultados observados ligados a la base/candidate identity.
- [x] 2.2 Reconciliar bindings, rutas de repositorio, worktrees, jobs/claims, audit trails, candidatos y migraciones aplicadas que deben conservarse; verificar que no se confunden referencias históricas con consumidores operativos.

## 3. Retiro de código y superficies

- [x] 3.1 Migrar consumidores legítimos a las rutas retenidas y retirar únicamente implementaciones, adaptadores, flags, endpoints, documentación y tests exclusivos demostrados obsoletos; verificar imports, DI, configuración, reflexión y scripts sin callers huérfanos.
- [x] 3.2 Repetir pruebas unitarias/integración, negativas y de regresión después de cada retiro; verificar que no queda una ruta duplicada activa ni un fallback silencioso y actualizar el Removal Ledger con diff y evidencia.

## 4. PostgreSQL y Alembic

- [x] 4.1 Confirmar para cada tabla/columna candidata sus lectores, writers, datos retenidos, foreign keys, backup, base de datos esperada y estrategia de rollback; verificar que una incertidumbre detiene la mutación.
- [x] 4.2 Implementar las migraciones Alembic mínimas y conservadoras y ejecutar upgrade, invariantes físicas, backup/retención y downgrade o rollback en la base explícitamente autorizada; verificar revisión, identidad DB y postcondiciones sin reparar automáticamente.

## 5. Reconciliación y borrado del fixture

- [x] 5.1 Reconciliar exactamente `mini-me-fixture` y `silverberdi/mini-me-r01-e2e-20261014`, incluidos bindings, worktrees, presupuesto, jobs/claims, tests, cierres y referencias durables; verificar que no existe dependencia operativa pendiente.
- [x] 5.2 Obtener y conservar la autorización humana expresa para el repositorio privado exacto, con alcance y destino de backup confirmados; verificar que sin esa autorización el repositorio permanece intacto y el Change queda HUMAN_REQUIRED.
- [x] 5.3 Ejecutar, solo tras 5.1–5.2, la acción externa exacta mediante el adaptador fail-closed y comprobar con una lectura autoritativa que el repositorio ya no existe; verificar que timeout/ambigüedad no provoca reintento ciego ni borra evidencia histórica.
- [x] 5.4 Escanear las referencias operativas restantes y conservar en el proyecto principal la evidencia histórica, SHAs, PRs, resultados y autorizaciones sin credenciales; verificar ausencia de referencias colgantes y no modificar Issues #1/#3/#5 ni PRs #2/#4 sin autorización separada.

## 6. Prueba real posterior y cierre técnico

- [x] 6.1 Ejecutar la suite final enfocada y la E2E real post-retiro contra las interfaces y servicios autorizados, incluyendo flujo retenido, invocaciones negativas de rutas retiradas, migración/rollback y postcondición del fixture; verificar salida, efectos y candidate SHA inmutable.
- [x] 6.2 Ejecutar revisión independiente read-only y verify nativo sobre el candidato final; verificar que la evidencia distingue PASS, FAIL, NOT_VERIFIED, WAITING_CAPACITY y HUMAN_REQUIRED y que no se acredita una integración con mocks o health 200.
- [x] 6.3 Confirmar que el diff no activa F7/F8, no despliega, no reinicia scheduler ni añade funcionalidades; verificar el límite de un único Change F6 y el estado final del Removal Ledger.

## 7. Entrega documental nativa

- [x] 7.1 Tras la autorización y merge de implementación correspondientes, crear rama fresca desde main y ejecutar sync/archive nativos del Change; verificar postcondiciones OpenSpec, PR documental, SHA y evidencia sin mover directorios manualmente.
- [x] 7.2 Completar el cierre conforme al contrato, incluyendo autorización humana, PRs/merges, resultados E2E, migración, reconciliación del fixture y referencias durables; verificar que el ticket remoto solo se cierra después del segundo merge y que no se afirma DONE ante evidencia faltante.
