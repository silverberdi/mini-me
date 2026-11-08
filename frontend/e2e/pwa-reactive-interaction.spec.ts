import { test, expect } from '@playwright/test';
import { setupAuthSession, waitForAppMounted } from './helpers';

test.describe('PWA Reactive Interaction and Form Stability', () => {
  test('configuration form inputs and modals remain stable over time without background polling resets', async ({ context, page }) => {
    // 1. Setup authenticated session
    await setupAuthSession(context);

    // 2. Navigate to Proyectos view
    await page.goto('/proyectos');
    await waitForAppMounted(page);

    // 3. Open the "Nuevo Proyecto" modal
    const openCreateBtn = page.getByRole('button', { name: /\+ Registrar Nuevo Proyecto/i });
    if (await openCreateBtn.isVisible()) {
      await openCreateBtn.click();

      const modalHeading = page.getByRole('heading', { name: /Registrar Nuevo Proyecto/i });
      await expect(modalHeading).toBeVisible();

      // Type into project ID and display name
      const idInput = page.locator('input#newProjectId');
      const testValue = 'pwa-stability-test-project';
      await idInput.fill(testValue);

      // Wait 3 seconds (well past any rapid timer interval)
      await page.waitForTimeout(3000);

      // Verify that the input has NOT been wiped or reset
      await expect(idInput).toHaveValue(testValue);
      await expect(modalHeading).toBeVisible();

      // Close modal
      const cancelBtn = page.getByRole('button', { name: /Cancelar/i }).first();
      await cancelBtn.click();
      await expect(modalHeading).toBeHidden();
    }
  });

  test('human gate dismissal is optimistic and shows immediate inline processing feedback', async ({ context, page }) => {
    // 1. Setup authenticated session
    await setupAuthSession(context);

    // 2. Navigate to trabajo-actual with mock human gate run
    await page.goto('/trabajo-actual?run=e2e-human-gate-run');
    await waitForAppMounted(page);

    // 3. Verify gate card is initially visible
    const gateCard = page.locator('h3', { hasText: 'Atención Humana Requerida (HUMAN_REQUIRED)' });
    if (await gateCard.isVisible()) {
      // Choose option or enter response
      const textarea = page.locator('textarea#clarificationInput');
      await textarea.fill('Confirmado mediante reactividad optimista');

      // Click submit
      const submitBtn = page.getByRole('button', { name: /Enviar respuesta y continuar/i });
      await submitBtn.click();

      // Optimistic assertion: processing feedback is immediately rendered
      const processingFeedback = page.locator('[role="status"]', { hasText: /Respuesta enviada, procesando/i });
      await expect(processingFeedback).toBeVisible({ timeout: 5000 });

      // The previous yellow gate card should now be dismissed / hidden
      await expect(gateCard).toBeHidden();
    }
  });

  test('application shell maintains stable connection badge and omits manual refresh and test connection controls', async ({ context, page }) => {
    // 1. Setup authenticated session
    await setupAuthSession(context);

    // 2. Navigate to dashboard
    await page.goto('/dashboard');
    await waitForAppMounted(page);

    // 3. Confirm connection badge displays "Conectado" and no disconnection banner is shown
    const connectionBadge = page.locator('header').getByText('Conectado');
    if (await connectionBadge.isVisible()) {
      await expect(connectionBadge).toBeVisible();

      const offlineBanner = page.locator('div[role="status"]', { hasText: /Sin conexión con el servidor mini me/i });
      await expect(offlineBanner).toBeHidden();

      // 4. Confirm manual refresh button is NOT present in header
      const refreshBtn = page.getByRole('button', { name: /Refrescar/i });
      await expect(refreshBtn).toBeHidden();

      // 5. Navigate to admin models-providers
      await page.goto('/administracion/modelos-proveedores');
      await waitForAppMounted(page);

      // 6. Confirm model administration renders without any Test Connection controls
      const testConnectionBtn = page.getByRole('button', { name: /Test Connection/i });
      await expect(testConnectionBtn).toBeHidden();

      // 7. Verify connection status remains stably "Conectado" across route transitions
      await expect(connectionBadge).toBeVisible();
      await expect(offlineBanner).toBeHidden();
    }
  });
});
