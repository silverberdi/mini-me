# Tasks

## 1. Definición y Estructura del Workflow de Validación

- [x] 1.1 Crear `.github/workflows/pr-validation.yml` configurando el trigger en eventos `pull_request` (`types: [opened, synchronize, reopened]`) dirigidos a la rama `main`.
- [x] 1.2 Configurar directivas de concurrencia `group: pr-validation-${{ github.event.pull_request.number || github.ref }}` con `cancel-in-progress: true` para cancelar ejecuciones obsoletas ante nuevos commits.
- [x] 1.3 Asignar permisos mínimos de solo lectura (`permissions: contents: read`) y prohibir inyección de secretos productivos o de despliegue.

## 2. Job de Validación de Backend

- [x] 2.1 Definir el job `backend-validation` sobre `ubuntu-latest` con el servicio `postgres:16-alpine` (base de datos `minime_test`, credenciales de prueba y healthcheck con `pg_isready`).
- [x] 2.2 Configurar paso de checkout del commit del PR y setup de Python 3.12 con caché de `pip`.
- [x] 2.3 Instalar el paquete en modo editable con dependencias de desarrollo (`pip install -e .[dev]`).
- [x] 2.4 Ejecutar las migraciones con `alembic upgrade head` conectando a `postgresql+psycopg://postgres:postgres@localhost:5432/minime_test`.
- [x] 2.5 Ejecutar la suite de pruebas vigente con `pytest` asegurando que cualquier fallo genere salida de error bloqueante.

## 3. Job de Validación de Frontend

- [x] 3.1 Definir el job `frontend-validation` sobre `ubuntu-latest` con checkout del código del PR.
- [x] 3.2 Configurar Node.js 20 con caché de npm vinculada a `frontend/package-lock.json`.
- [x] 3.3 Instalar dependencias del frontend de forma determinista mediante `npm ci` en el directorio `frontend/`.
- [x] 3.4 Ejecutar las pruebas unitarias del frontend (`npm test`, que ejecuta `node --test tests/*.test.mjs`).
- [x] 3.5 Compilar la aplicación Angular (`npm run build`) verificando que genere los artefactos sin errores y termine con código de retorno 0.

## 4. Consolidación del Gate y Verificación

- [x] 4.1 Añadir el job sintetizador `pr-gate` con `needs: [backend-validation, frontend-validation]` que emita el estado final del gate para configuración como Required status check en GitHub.
- [x] 4.2 Validar la corrección sintáctica y de esquema YAML del workflow `.github/workflows/pr-validation.yml`.
- [x] 4.3 Verificar que el flujo de release y despliegue en `.github/workflows/release-and-deploy.yml` permanezca intacto y desligado de los eventos de Pull Request.
