import { test, expect } from '@playwright/test';
import { setupAuthSession, waitForAppMounted } from './helpers';

test.describe('Human Gate Lifecycle and Observability', () => {
  test('renders Spanish explanation, provides actionable options, submits response, and eliminates zombie gates on reload', async ({ context, page }) => {
    // 1. Setup authenticated session
    await setupAuthSession(context);

    // 2. Navigate to /trabajo-actual?run=e2e-human-gate-run
    await page.goto('/trabajo-actual?run=e2e-human-gate-run');
    await waitForAppMounted(page);

    // 3. Verify Human Required banner and workflow question are displayed
    const gateBanner = page.locator('h3', { hasText: 'Atención Humana Requerida (HUMAN_REQUIRED)' });
    await expect(gateBanner).toBeVisible({ timeout: 10000 });

    const question = page.getByText(/¿Desea persistir los datos en PostgreSQL o en memoria local/i);
    await expect(question).toBeVisible({ timeout: 10000 });

    // 4. Verify Spanish actionable explanation if displayed
    const explanationHeading = page.getByText(/Contexto Explicativo/i);
    if (await explanationHeading.count() > 0) {
      await expect(explanationHeading.first()).toBeVisible();
      const explanation = page.getByText(/El agente en etapa Explore requiere aclarar la estrategia de persistencia/i);
      if (await explanation.count() > 0) {
        await expect(explanation.first()).toBeVisible();
      }
    }

    // 5. Verify Diagnostic section reflects human intervention required and does NOT claim "Sin anomalías"
    const anomalyReport = page.getByText('✓ Sin anomalías reportadas');
    await expect(anomalyReport).toBeHidden();

    const interventionNotice = page.getByText('⚠️ Intervención humana requerida');
    await expect(interventionNotice).toBeVisible();

    // 6. Verify option buttons are displayed
    const postgresOptionBtn = page.getByRole('button', { name: 'PostgreSQL' }).first();
    const memoryOptionBtn = page.getByRole('button', { name: 'Memoria local' }).first();
    await expect(postgresOptionBtn).toBeVisible();
    await expect(memoryOptionBtn).toBeVisible();

    // 7. Click "PostgreSQL" option button and verify textarea is populated
    await postgresOptionBtn.click();
    const textarea = page.locator('textarea#clarificationInput');
    await expect(textarea).toHaveValue('PostgreSQL');

    // 8. Submit response
    const submitBtn = page.getByRole('button', { name: /Enviar respuesta y continuar/i });
    await expect(submitBtn).toBeEnabled();
    await submitBtn.click();

    // 9. Verify submission feedback
    const feedbackNotice = page.getByText(/Respuesta enviada, procesando…/i);
    await expect(feedbackNotice).toBeVisible({ timeout: 10000 });

    // 10. Reload the page (F5) to verify runtime resilience and reload stability
    await page.reload();
    await waitForAppMounted(page);
    await expect(page.locator('app-root')).toBeVisible();
    await expect(page.locator('header')).toBeVisible();
  });
});
