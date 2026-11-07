# Proposal

## Why

El repositorio de mini me cuenta actualmente con pruebas unitarias en memoria para el frontend (`node --test`) y pruebas de integración aisladas para el backend, pero carece de pruebas E2E en navegador real. Esto impide detectar regresiones reales en los recorridos críticos de la interfaz de usuario donde convergen el DOM de Angular, los endpoints de FastAPI y la persistencia en PostgreSQL tras recargas de página. Conforme al [Contrato Rector v2.0](docs/CONTRATO_RECTOR.md) (§1, §2) y tras haberse consolidado el workflow de CI en PRs de PODA 2 (#317), es indispensable disponer de pruebas E2E auténticas, reproducibles y deterministas sobre la UI servida.

## What Changes

- Incorporar Playwright (`@playwright/test`) como arnés ligero y determinista de pruebas E2E en `frontend/` ejecutando Chromium en modo headless.
- Implementar 3 recorridos críticos de alto riesgo basados estrictamente en las acciones visibles de la UI actual:
  1. **Pausa y Reanudación de Proyecto:** Operación en UI desde la vista de Proyectos, mutación de estado en backend/PostgreSQL, actualización del badge reactivo en el DOM y verificación de persistencia tras recarga de página (`F5`).
  2. **Administración y Toggle de Modelos:** Navegación a `/administracion/modelos-proveedores`, conmutación del switch de activación de modelo, persistencia en BD y reflejo visual.
  3. **Flujo Negativo y Manejo de Error:** Acción inválida o simulación de error de red comprobando que la UI muestra feedback accesible sin romper el runtime de Angular.
- Configurar el entorno de ejecución efímero para E2E (FastAPI sirviendo la aplicación + PostgreSQL efímero con migraciones Alembic aplicadas).
- Incorporar el job `e2e-validation` en `.github/workflows/pr-validation.yml` conectado a `pr-gate`.
- Asegurar aislamiento estricto: prohibido el acceso a la base de datos de producción, llamadas a proveedores LLM de pago y despliegues.

## Capabilities

### New Capabilities

- `ui-browser-e2e-verification`: Verificación automatizada en navegador real de los flujos críticos de la interfaz de usuario, su persistencia durable y su integración con el gate de CI.

### Modified Capabilities

- None.

## Impact

- Frontend: adición de devDependency `@playwright/test` en `frontend/package.json`, configuración `frontend/playwright.config.ts` y tests en `frontend/e2e/`.
- CI/CD: incorporación del job `e2e-validation` en `.github/workflows/pr-validation.yml`.
- Sin impacto en APIs productivas, esquemas de base de datos ni en el flujo de despliegue (`release-and-deploy.yml`).
