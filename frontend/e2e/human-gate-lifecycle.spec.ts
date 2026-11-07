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

    // 4. Verify Spanish actionable explanation is displayed
    const explanationHeading = page.getByText(/Contexto Explicativo/i);
    await expect(explanationHeading).toBeVisible({ timeout: 10000 });
    const explanation = page.getByText(/El agente en etapa Explore requiere aclarar la estrategia de persistencia/i);
    await expect(explanation).toBeVisible({ timeout: 10000 });

    // 5. Verify Diagnostic section reflects human intervention required and does NOT claim "Sin anomalías"
    const anomalyReport = page.locator('div', { hasText: '✓ Sin anomalías reportadas' });
    await expect(anomalyReport).toBeHidden();

    const interventionNotice = page.locator('div', { hasText: '⚠️ Intervención humana requerida' });
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
    const feedbackNotice = page.locator('div', { hasText: /Respuesta enviada, procesando…/i });
    await expect(feedbackNotice).toBeVisible({ timeout: 10000 });

    // 10. Reload the page (F5) to verify PostgreSQL persistence and ensure no zombie gate resurfaces
    await page.reload();
    await waitForAppMounted(page);

    // The gate banner and question should now be gone (gate was resolved)
    await expect(page.locator('h3', { hasText: 'Atención Humana Requerida (HUMAN_REQUIRED)' })).toBeHidden({ timeout: 10000 });

    // Diagnóstico section now shows "Sin anomalías reportadas"
    await expect(page.locator('div', { hasText: '✓ Sin anomalías reportadas' })).toBeVisible();
    await expect(page.locator('div', { hasText: '⚠️ Intervención humana requerida' })).toBeHidden();
  });
});
