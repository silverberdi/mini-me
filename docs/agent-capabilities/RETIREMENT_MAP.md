# Removal Targets by Vertical Change — censo inicial

**No es una orden de borrado.** Los paths se identifican a partir de la arquitectura inspeccionada; en `design.md` el agente debe examinar referencias reales/dinámicas y clasificar REMOVE/MIGRATE/RETAIN-WITH-REASON. Nunca asumir que un archivo entero carece de usos porque una función ha sido reemplazada. Históricos de OpenSpec/DB/Git y migraciones aplicadas **se conservan**.

| Change | Implementación que podría quedar obsoleta | Nuevo propietario de comportamiento | Prueba para retirar |
|---|---|---|---|
| R01 | prompts de código no OpenSpec en `src/minime/services/execution_pipeline.py`, rutas ad hoc en `implementer_runner.py` | Agente con workflow OpenSpec `apply` real, mini me solo dispatch | PR E2E con trace de skill, reviewers y tests tras retiro |
| R02 | escritor de plantilla `src/minime/services/openspec_generator.py`, llamada desde `intake_service.py`, tests `test_canonical_artifact_generation.py` con autoridad falsa | Agente `propose` para semántica; mini me intake/idempotency | Issue→proposal multi-spec real, anti-drift, replay sin duplicados, tests migrados |
| R03 | decisiones de stage en `orchestration_service.py` y prompts legacy de `execution_pipeline.py` que sustituyan OpenSpec, adaptadores duplicados | Un dispatcher stage-aware + scheduler y sagas existentes | 2 Changes reales autónomos, crash/restart, paths legacy no alcanzables |
| R04 | writers semánticos propios de `openspec_sync.py` y callers `post_merge_service.py` de sync/archive | Agente/nativo OpenSpec + saga de cierre de mini me | native delta E2E, branch protegido, postdeploy, no writers redundantes |
| R05 | probes/flags de cuota que reporten `available` stale o reintentos no conservadores | Provider health + stage preflight + durable recovery | auth/quota E2E y same Run/Job tras restart |
| R06 | catálogos/harnesses duplicados, hooks no conectados o skills redundantes | Catálogo mínimo con manifests y versión; PR #140 si aceptado | invocación real con trace + denegación adversarial |
| R07 | read models/UI duplicados o comandos de operador que saltan control plane | Una API/servicio de estado y acciones autorizado | browser desktop/tablet/mobile real + idempotencia |
| R08 | condiciones `mini-me-only` en rutas genéricas, hardcoded remote/root | Managed-repository config verificada por repo | 2 repos E2E y prueba de aislamiento |
| R09 | prototipos/scripts de skills reemplazados sin consumidor | Biblioteca versionada de skills/hooks/harness | ejecución real de capacidad nueva por otro Change |
| R10 | handoffs operativos manuales que ya no tienen consumidores, no gates humanos | Loop autónomo con human merge | Issue→PR→merge humano→deploy→E2E→siguiente item |

## Lo que NO se retira por “limpieza”
- Ledger de N01, Runs/Jobs/attempts, durable sagas, event histories, worktrees dirty, OpenSpec archivado, migraciones aplicadas.
- `OpenSpecAdapter` y validadores existentes mientras cumplan checks oficiales.
- Scheduler, Postgres/claim/fencing, guards, Git worktree y GitHub integrations si su función sigue siendo de orquestación legítima.
- Motor de PR #140 que aún no está fusionado; primero revisión independiente, decidir si adopción o rechazo documentado.
- Harness local de Qwen con patch applier si existe uso autorizado/histórico que dependa de él; tampoco contarlo como OpenSpec runner sin pruebas.

## Gate de retiro
1. Escribir ledger de consumidores.
2. Probar nueva ruta E2E real.
3. Migrar entradas, configuraciones, test contratos, docs.
4. Retirar porciones efectivamente obsoletas en **el mismo Change**.
5. Ejecutar tests y E2E **después** de retirar.
6. Verificar despliegue, no writers fantasma, no fallback silencioso; permitir RETAIN-WITH-REASON solo con aprobación humana y sunset explícito.
