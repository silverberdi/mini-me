# Tasks

## 1. Configuración del Arnés de Playwright

- [x] 1.1 Añadir `@playwright/test` como devDependency en `frontend/package.json`.
- [x] 1.2 Crear archivo de configuración `frontend/playwright.config.ts` acotado a Chromium headless, con auto-waiting y directiva `webServer` para orquestar FastAPI y estáticos de Angular.
- [x] 1.3 Configurar script `"test:e2e": "playwright test"` en `frontend/package.json`.

## 2. Implementación de los Recorridos Críticos E2E

- [x] 2.1 Crear utilidades de soporte y sembrado de estado efímero en `frontend/e2e/helpers.ts`.
- [x] 2.2 Implementar prueba E2E del ciclo de pausa y reanudación de proyecto con persistencia tras recarga (`F5`) en `frontend/e2e/project-pause-resume.spec.ts`.
- [x] 2.3 Implementar prueba E2E de navegación a `/administracion/modelos-proveedores` y toggle de activación de modelo en `frontend/e2e/admin-models-toggle.spec.ts`.
- [x] 2.4 Implementar prueba E2E de notificación y resiliencia ante errores observables sin colapso de UI en `frontend/e2e/error-feedback.spec.ts`.

## 3. Integración en el Pipeline de CI y Compuerta de PR

- [x] 3.1 Definir el job `e2e-validation` en `.github/workflows/pr-validation.yml` con PostgreSQL efímero migrado, instalación de Chromium headless (`npx playwright install --with-deps chromium`) y ejecución de `npm run test:e2e`.
- [x] 3.2 Actualizar el job `pr-gate` en `.github/workflows/pr-validation.yml` para requerir `needs: [backend-validation, frontend-validation, e2e-validation]`.
- [x] 3.3 Validar la corrección sintáctica YAML del workflow modificado.
- [x] 3.4 Ejecutar la suite E2E completa verificando que finalice con código 0 y tiempo menor a 30 segundos.
