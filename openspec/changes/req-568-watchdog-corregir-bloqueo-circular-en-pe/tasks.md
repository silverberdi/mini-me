# Tasks

## 1. Persistencia incondicional de diagnosticos Watchdog

- [x] 1.1 Modificar WatchdogObservationService y minime/cli/main.py para persistir la observacion diagnostica con su clave de transicion e identidad de evento sin condicionar el primer guardado a un registro previo; verificar con prueba unitaria en tests/test_watchdog_service.py.
- [x] 1.2 Asegurar que PostgresWatchdogRepository.save_diagnosis preserve la clave de transicion y sea idempotente ante entregas duplicadas del mismo evento; verificar con prueba en tests/test_watchdog_repository.py.

## 2. Deteccion de recurrencias y almacenamiento de sugerencias

- [x] 2.1 Actualizar la evaluacion de recurrencia en watchdog_service.py para consultar registros previos por clave de transicion e identidad de evento; verificar con prueba unitaria que una segunda observacion detecta el patron.
- [x] 2.2 Almacenar la sugerencia de mejora continua generada por el analizador semantico con estado pending en watchdog_diagnoses; verificar con prueba unitaria de persistencia y serializacion.

## 3. Exposicion en API administrativa y verificacion E2E

- [x] 3.1 Verificar y asegurar que /api/v1/admin/watchdog/diagnoses devuelva las sugerencias con estado pending para consumo de la vista /mejora-continua; verificar con prueba de integracion API en tests/test_admin_diagnoses_api.py.
- [x] 3.2 Ejecutar la suite de pruebas pertinentes de watchdog y admin (pytest -q tests/test_watchdog_service.py tests/test_watchdog_repository.py tests/test_watchdog_dirty_worktree_recovery_e2e.py tests/test_admin_diagnoses_api.py) asegurando codigo de salida 0 y evidencia observable de la persistencia y respuesta administrativa.

> Evidencia: La suite pertinente del Change (pytest -q tests/test_watchdog_service.py tests/test_watchdog_repository.py tests/test_watchdog_dirty_worktree_recovery_e2e.py tests/test_admin_diagnoses_api.py) ejecuto 18 pruebas con codigo de salida 0 (18 passed, 0 skipped, 0 failed) sobre base de datos PostgreSQL de pruebas (minime_test). Se verifico la persistencia incondicional del primer diagnostico Watchdog con su clave de transicion e identidad de evento, la deduplicacion idempotente en repositorios PostgreSQL, la deteccion de recurrencias por clave de transicion, la serializacion de sugerencias de mejora continua con estado pending y su correcta exposicion en el endpoint administrativo /api/v1/admin/watchdog/diagnoses.
