# Proposal

## Why

Actualmente el repositorio de mini me cuenta con un único workflow de GitHub Actions (`release-and-deploy.yml`) que se ejecuta tras el merge a `main`, sin contar con una compuerta automatizada de integración continua previa en los Pull Requests. Esto expone a la rama principal a recibir regresiones silenciosas en backend o frontend antes de que el código sea integrado. Conforme al [Contrato Rector v2.0](docs/CONTRATO_RECTOR.md) y tras haberse completado la depuración de código de PODA 1 (#316), es indispensable validar de forma determinista y aislada cada PR antes de permitir su incorporación.

## What Changes

- Crear un workflow dedicado de validación en GitHub Actions (`.github/workflows/pr-validation.yml`) que se activa en eventos de Pull Request hacia la rama `main`.
- Ejecutar la suite de pruebas backend vigente con `pytest` en un entorno con PostgreSQL efímero (`services: postgres`) y migraciones de esquema aplicadas con `alembic upgrade head`.
- Ejecutar las pruebas unitarias frontend conservadas y compilar la PWA Angular (`ng build`).
- Garantizar aislamiento estricto: prohibido el acceso a la base de datos de producción, llamadas a proveedores o APIs externas de pago, y cualquier intento de despliegue dentro del ciclo de PR.
- Publicar resultados inequívocos vinculados al commit SHA probado para que actúen como status check bloqueante ante cualquier fallo de pruebas o compilación.
- Preservar intacto e independiente el flujo de release y despliegue posterior al merge en `main`.

## Capabilities

### New Capabilities

- `pull-request-validation-gate`: Validación continua obligatoria en eventos de Pull Request mediante GitHub Actions, ejecutando pruebas backend con base PostgreSQL efímera y pruebas/compilación frontend en aislamiento total de entornos productivos y servicios tarificados.

### Modified Capabilities

- None.

## Impact

- Infraestructura CI/CD: creación del archivo de workflow `.github/workflows/pr-validation.yml`.
- Configuración de repositorio: provisión del nombre de check determinista para que el operador lo marque como Required status check en las reglas de protección de rama de `main`.
- Entornos de ejecución: aprovisionamiento automático de contenedor efímero PostgreSQL 16 y Node.js/Python en los runners de GitHub Actions.
- Sin impacto en código productivo de aplicación ni en el flujo de despliegue (`release-and-deploy.yml`).
