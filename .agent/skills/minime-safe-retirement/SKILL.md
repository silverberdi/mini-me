---
name: minime-safe-retirement
description: "Retirar código muerto y rutas suplantadas dentro del mismo Change, sin perder historia ni regresiones."
---
# mini me — Safe Code Retirement (v1)

**Skill de apoyo para el OpenSpec apply/verify del mismo Change que sustituye una función.** Autoridad: `docs/ENGINEERING_DISCIPLINE.md` §4. Trabaja solo en el worktree asignado.

## Removal Ledger obligatorio
Por cada comportamiento reemplazado registra: viejo entrypoint/writers; referencias/callers; DI/API/CLI/jobs/guards/hooks/config/tests; side effects; datos y migraciones históricas a conservar; ruta OpenSpec/agente sustituta; acción REMOVE/MIGRATE/RETAIN-WITH-REASON; prueba de paridad; evidencia después de borrado.

## Procedimiento
1. Enumerar llamadas estáticas **y** rutas dinámicas/configuraciones. Un símbolo sin referencias textuales puede seguir en uso.
2. Ejecutar E2E del reemplazo con OpenSpec y agentes reales antes de eliminar lo antiguo.
3. Migrar consumidores, contratos y tests, sin borrar protección de regresión; versionar APIs o migraciones si corresponden.
4. Retirar writers viejos, flags de transición sin consumidores, adaptadores redundantes, scripts y dependencias huérfanos.
5. **Repetir** unit/integration, seguridad, E2E por etapa, E2E de valor, E2E postdeploy y regresiones **después** de la eliminación. Comprobar que un arranque real no elige rutas retiradas.
6. Cuando histórico/seguridad impidan retiro: RETAIN-WITH-REASON + ruta deshabilitada, riesgo, dueño, fecha/condición de sunset y aprobación humana. No declarar desmonte terminado si sigue alcanzable.

## Candidatos (nunca borrar por nombre)
R01/R03: prompts y dispatch antiguos de implementación; R02: `src/minime/services/openspec_generator.py` y callers; R04: writers de sync/archive en `src/minime/services/openspec_sync.py`; R06: registries/hooks/harness duplicados. Conserva los servicios de validación, gates, sagas y reconciliación **si aún son necesarios**.

Devuelve tabla ledger final con SHA, código retirado, callers migrados, pruebas reejecutadas y evidencia postdeploy. No uses un prompt libre para programar.
