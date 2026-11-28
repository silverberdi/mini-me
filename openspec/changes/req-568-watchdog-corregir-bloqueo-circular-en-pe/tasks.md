# Tasks

## 1. Persistencia incondicional de diagnosticos Watchdog

- [x] 1.1 Modificar WatchdogObservationService y minime/cli/main.py para persistir la observacion diagnostica con su clave de transicion e identidad de evento sin condicionar el primer guardado a un registro previo; verificar con prueba unitaria en tests/test_watchdog_service.py.
- [x] 1.2 Asegurar que PostgresWatchdogRepository.save_diagnosis preserve la clave de transicion y sea idempotente ante entregas duplicadas del mismo evento; verificar con prueba en tests/test_watchdog_repository.py.

## 2. Deteccion de recurrencias y almacenamiento de sugerencias

- [x] 2.1 Actualizar la evaluacion de recurrencia en watchdog_service.py para consultar registros previos por clave de transicion e identidad de evento; verificar con prueba unitaria que una segunda observacion detecta el patron.
- [x] 2.2 Almacenar la sugerencia de mejora continua generada por el analizador semantico con estado pending en watchdog_diagnoses; verificar con prueba unitaria de persistencia y serializacion.

## 3. Exposicion en API administrativa y verificacion E2E

- [x] 3.1 Verificar y asegurar que /api/v1/admin/watchdog/diagnoses devuelva las sugerencias con estado pending para consumo de la vista /mejora-continua; verificar con prueba de integracion API en tests/test_admin_diagnoses_api.py.
- [ ] 3.2 Ejecutar la suite de pruebas pertinentes de watchdog y admin (pytest tests/test_watchdog*.py) asegurando codigo de salida 0 y evidencia observable de la persistencia y respuesta administrativa.

> Evidencia parcial: `pytest -q tests/test_watchdog*.py tests/test_admin_diagnoses_api.py` terminó con código 0 (`33 passed, 1 skipped`). La E2E PostgreSQL de recuperación y persistencia pasó; el único skip corresponde al escenario de proveedor real no configurado. La persistencia ahora usa la identidad de evento junto con run/etapa/candidato, permite eventos distintos y mantiene el replay idempotente; la migración `req568_watchdog_event_identity` quedó aplicada al PostgreSQL de pruebas. Falta evidencia candidata de una invocación real del proveedor SRE y sus efectos persistidos: este worktree no tiene configurados `MINIME_SRE_E2E_PROVIDER_ID`, `MINIME_SRE_E2E_HARNESS_ID` ni `MINIME_SRE_E2E_MODEL_ID`; el test no se marca como completado mientras esa E2E no se ejecute sin skip.
