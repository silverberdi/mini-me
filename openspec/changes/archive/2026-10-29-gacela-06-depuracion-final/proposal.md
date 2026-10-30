# Proposal

## Why

F6 debe cerrar la reconstrucción F1–F6 retirando los restos obsoletos que sobrevivan a F5 sin introducir capacidades de F7/F8. Ahora corresponde convertir el censo real de código, consumidores, PostgreSQL, documentación, tests y fixture E2E heredado en una retirada verificable, reversible cuando afecte datos, y ejecutada de principio a fin por mini me.

## What Changes

- Censar componentes, callers, writers, endpoints, flags, dependencias, tests, migraciones, worktrees, jobs/claims, bindings y referencias durables que F5 ya no necesite; clasificar cada elemento como REUSE, MODIFY, REMOVE o RETAIN-WITH-REASON.
- Retirar, dentro de este único Change, las rutas y abstracciones duplicadas u obsoletas demostradas sin consumidores, repitiendo las pruebas pertinentes después del retiro y conservando historia OpenSpec, auditoría, SHAs y datos operativos necesarios.
- Aplicar únicamente migraciones Alembic seguras para tablas/columnas no usadas, con backup, preservación de datos, rollback probado y separación estricta del PostgreSQL operativo y cualquier base desechable.
- Confirmar antes de retirar que F2–F5 y los cierres/pruebas activos no dependen del fixture E2E; inventariar y reconciliar `mini-me-fixture`, sus bindings, worktrees, presupuesto, jobs/claims y referencias.
- Ejecutar E2E real post-retiro que demuestre el recorrido retenido, ausencia de rutas obsoletas y efectos observables de la limpieza; conservar la evidencia necesaria en el proyecto principal sin credenciales.
- Eliminar irreversiblemente, solo tras autorización humana expresa y confirmación de alcance, el repositorio privado `silverberdi/mini-me-r01-e2e-20261014`; verificar después su ausencia y la inexistencia de referencias operativas colgantes. Esta planificación no ejecuta ese borrado.
- Mantener F7 (#189), F8 (#190), despliegues, migraciones de datos no justificadas, scheduler y nuevas funcionalidades fuera de alcance.

## Capabilities

### New Capabilities

- `f6-final-retirement`: contrato observable para la depuración final, retirada segura de superficies obsoletas, limpieza PostgreSQL reversible, reconciliación del fixture heredado y prueba E2E posterior.

### Modified Capabilities

<!-- F6 añade un contrato específico; las capacidades existentes de legacy,
     PostgreSQL, binding, worktree y evidencia se reutilizan sin duplicarlas. -->
- Ninguna.

## Impact

Código y configuración de mini me que permanezcan tras F5; rutas API/CLI/UI y servicios heredados; modelos SQLAlchemy y migraciones Alembic; tests y fixtures; registros PostgreSQL de proyecto, continuidad, jobs/claims y bindings; worktrees y repositorios administrados; GitHub/Git y el CLI/workflows nativos de OpenSpec. No se autoriza cambio en la API funcional de F7/F8 ni despliegue productivo.
