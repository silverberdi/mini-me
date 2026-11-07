# Design

## Context

El repositorio cuenta actualmente con un único workflow de GitHub Actions ([`release-and-deploy.yml`](.github/workflows/release-and-deploy.yml)) que reacciona a eventos `push` en la rama `main`, empaqueta el frontend y despliega la aplicación. No existe ninguna compuerta de validación previa en los Pull Requests, lo que expone a la rama principal a incorporar cambios con pruebas rotas o fallos de compilación.

El backend de mini me requiere Python >= 3.12, dependencias gestionadas mediante `pyproject.toml` (incluyendo `[project.optional-dependencies] dev` para `pytest`), persistencia en PostgreSQL con migraciones Alembic. El frontend reside en el directorio `frontend/`, implementado en Angular y gestionado con Node.js 20 / npm (`npm test` y `npm run build`).

## Goals / Non-Goals

**Goals:**
- Implementar `.github/workflows/pr-validation.yml` activado en eventos `pull_request` (`opened`, `synchronize`, `reopened`) dirigidos a `main`.
- Validar backend en paralelo ejecutando migraciones `alembic upgrade head` y `pytest` contra un contenedor efímero de PostgreSQL 16.
- Validar frontend en paralelo ejecutando pruebas unitarias (`npm test`) y compilación (`npm run build`).
- Proveer un resultado de status check determinista e inequívoco sobre el SHA del candidato para permitir la configuración de reglas de protección en GitHub.
- Garantizar aislamiento absoluto de recursos productivos y proveedores externos tarificados.

**Non-Goals:**
- Modificar o alterar el workflow existente de release y despliegue posterior al merge.
- Implementar suites de pruebas E2E de navegador completas con Cypress o Playwright (reservado para PODA 3).
- Configurar programáticamente las Branch Protection Rules de GitHub desde el workflow (la activación del check como requerido corresponde a la configuración del repositorio por el operador).

## Decisions

### Decisión 1: Jobs separados y paralelos para Backend y Frontend
- **Opción elegida:** Dividir la validación en dos jobs independientes: `backend-validation` y `frontend-validation`, con un job sintetizador o de puerta `pr-validation-gate` que dependa de ambos.
- **Razón:** Maximiza el paralelismo en los runners de GitHub Actions, reduce el tiempo de feedback y permite aislar con claridad si una falla proviene de Python/PostgreSQL o de Angular/Node.js.
- **Alternativas consideradas:** Un único job monolítico secuencial (descartado por tiempos de ejecución lentos y menor claridad diagnóstica).

### Decisión 2: Servicio PostgreSQL efímero nativo en el runner
- **Opción elegida:** Utilizar la directiva `services: postgres` con la imagen oficial `postgres:16-alpine`, comprobación de salud (`pg_isready`) y base de datos desechable (`minime_test`).
- **Razón:** Proporciona un entorno PostgreSQL idéntico al motor de producción sin depender de SQLite o mocks, permitiendo verificar que las migraciones de Alembic apliquen limpiamente.
- **Alternativas consideradas:** Mockear la base de datos o usar SQLite en memoria (descartado por violar la regla de pruebas reales y no validar tipos específicos de PostgreSQL ni migraciones).

### Decisión 3: Ejecución de pruebas frontend mediante Node.js test runner y compilación de producción
- **Opción elegida:** Ejecutar `npm test` (que ejecuta el test runner nativo de Node.js `node --test tests/*.test.mjs`) seguido de `npm run build` (`ng build --configuration production`).
- **Razón:** La suite de pruebas de frontend está construida con el runner nativo de Node.js (38 pruebas unitarias) sin requerir navegadores pesados ni dependencias de Karma/Chromium, lo que garantiza tiempos de ejecución ultrarrápidos (~300ms) y deterministas en el runner de CI.
- **Alternativas consideradas:** Añadir navegadores headless con Karma/Playwright (descartado por innecesario y por estar fuera de alcance en este Issue, reservado para PODA 3).

### Decisión 4: Aislamiento estricto de secretos y entorno productivo
- **Opción elegida:** El workflow no consume secretos de despliegue (`KUBE_CONFIG`, `SSH_KEY`, claves de producción) ni variables de proveedores LLM. Las credenciales de base de datos son exclusivamente locales al runner (`postgres:postgres@localhost:5432/minime_test`).
- **Razón:** Cumplimiento no negociable del Contrato Rector v2.0 contra costos y modificaciones accidentales en producción.

## Risks / Trade-offs

- **[Riesgo de lentitud por descarga de paquetes en cada run]** → *Mitigación:* Configurar `cache: 'pip'` en `actions/setup-python` y `cache: 'npm'` con `cache-dependency-path: frontend/package-lock.json` en `actions/setup-node`.
- **[Riesgo de dependencias frontend no deterministas]** → *Mitigación:* Utilizar estrictamente `npm ci` en lugar de `npm install`.
- **[Riesgo de desincronización de migraciones en la base efímera]** → *Mitigación:* Ejecutar explícitamente `alembic upgrade head` como paso previo a la invocación de `pytest`.
