# Design

## Context

mini me cuenta con pruebas unitarias de frontend (`node --test`) y suite de pruebas de backend con `pytest`. Sin embargo, hasta la fecha no existe ninguna prueba que arranque el sistema completo de forma integrada (servidor web FastAPI + persistencia PostgreSQL + navegador real operando sobre la PWA Angular compilada). El [Contrato Rector v2.0](docs/CONTRATO_RECTOR.md) exige que toda entrega de software cuente con evidencia observable y E2E real, pero respetando el principio de «la gacela, no el paquidermo» (menor solución suficiente, sin crear burocracias ni suites lentas y quebradizas).

## Goals / Non-Goals

**Goals:**
- Configurar `@playwright/test` en `frontend/` configurado exclusivamente para Chromium headless con auto-waiting y timeouts acotados.
- Implementar 3 tests E2E deterministas sobre los flujos críticos visibles:
  1. Pausa y reanudación de proyecto con verificación de persistencia tras recarga (`F5`).
  2. Administración de modelos en `/administracion/modelos-proveedores` con persistencia en PostgreSQL.
  3. Manejo de error visible en pantalla sin fallo catastrófico del runtime de Angular.
- Configurar `playwright.config.ts` con la opción `webServer` para orquestar el inicio y parada del servidor FastAPI y el servicio de estáticos compilados.
- Añadir el job `e2e-validation` en `.github/workflows/pr-validation.yml` asegurando que la suite completa se ejecute en menos de 30 segundos.

**Non-Goals:**
- Construir matrices de pruebas exhaustivas para múltiples navegadores (Firefox, WebKit); Chromium headless es suficiente para garantizar la integración.
- Probar llamadas reales a proveedores LLM de pago en CI (se usan adaptadores locales de diagnóstico).
- Modificar el comportamiento o diseño de los componentes Angular existentes.

## Decisions

### Decisión 1: Adopción de Playwright (`@playwright/test`) en `frontend/`
- **Opción elegida:** Integrar Playwright en el entorno Node.js del frontend (`frontend/package.json`).
- **Razón:** Playwright ofrece auto-waiting inteligente de elementos DOM (eliminando retardos artificiales o flaky tests), soporte nativo para `webServer` y comandos de instalación acotados a un único motor (`npx playwright install --with-deps chromium`).
- **Alternativas consideradas:** Cypress (más pesado, tiempo de arranque más lento y configuración más compleja en GitHub Actions) o Selenium (obsoleto para PWAs modernas).

### Decisión 2: Acotar a 3 recorridos críticos de alto riesgo
- **Opción elegida:** Limitar la suite inicial a tres recorridos clave:
  1. *Proyecto:* Operación de mutación, actualización reactiva y comprobación de persistencia tras `F5`.
  2. *Admin de modelos:* Navegación SPA y mutación PATCH a la base de datos.
  3. *Resiliencia:* Reacción visual ante errores de red o validación sin pantalla en blanco.
- **Razón:** Cumple plenamente con el alcance de PODA 3 sin inflar los tiempos de CI ni sobrecargar de mantenimiento al proyecto.
- **Alternativas consideradas:** Cubrir todas las páginas y botones de la aplicación (descartado por violar KISS/YAGNI).

### Decisión 3: Orquestación del servidor mediante `webServer` de Playwright
- **Opción elegida:** En `playwright.config.ts`, utilizar la propiedad `webServer` para ejecutar `uvicorn minime.api.app:app --port 8788` con `MINIME_DATABASE_URL` efímero, sirviendo los estáticos generados por `npm run build`.
- **Razón:** Garantiza que Playwright espere a que el puerto HTTP esté saludable (`url: http://localhost:8788/health/live`) antes de lanzar el navegador y que limpie el proceso automáticamente al terminar.
- **Alternativas consideradas:** Scripts de bash en segundo plano con `nohup` y `sleep` (descartado por fragilidad y riesgo de procesos huérfanos).

### Decisión 4: Integración en `.github/workflows/pr-validation.yml`
- **Opción elegida:** Añadir el job `e2e-validation` que se ejecuta sobre `ubuntu-latest`, instala solo Chromium (`npx playwright install --with-deps chromium`), levanta el servicio PostgreSQL efímero y corre `npx playwright test`.
- **Razón:** Permite que `pr-gate` dependa de `[backend-validation, frontend-validation, e2e-validation]`, garantizando el bloqueo automático de merge si algún test de navegador falla.

## Risks / Trade-offs

- **[Riesgo de lentitud por instalación de navegadores en CI]** → *Mitigación:* Instalar exclusivamente Chromium (`npx playwright install --with-deps chromium`), lo que toma menos de 15 segundos en el runner.
- **[Riesgo de condición de carrera con SSE o WebSockets]** → *Mitigación:* Usar selectores basados en accesibilidad y auto-waiting (`expect(page.getByRole(...)).toBeVisible()`) en lugar de timers fijos.
- **[Riesgo de conflicto de base de datos]** → *Mitigación:* Ejecutar `alembic upgrade head` sobre una base de datos efímera dedicada antes de iniciar la suite.
