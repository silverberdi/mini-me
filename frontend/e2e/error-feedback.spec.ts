import { test, expect } from '@playwright/test';
import { resetModelEnablement, setupAuthSession, waitForAppMounted, TEST_MODEL_ID } from './helpers';

test.describe('Observable Error Feedback and Runtime Resilience', () => {
  test.beforeEach(async ({ request }) => {
    await resetModelEnablement(request, TEST_MODEL_ID);
  });

  test.afterEach(async ({ request }) => {
    await resetModelEnablement(request, TEST_MODEL_ID);
  });

  test('displays observable error notification upon API failure without crashing Angular shell', async ({ context, page }) => {
    // 1. Setup authenticated session and register route interceptor for error simulation
    await setupAuthSession(context);

    await page.route(/\/api\/v1\/admin\/providers\/models\/.*\/enabled/, async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Error de servidor simulado para prueba E2E' }),
      });
    });

    // 2. Navigate to /administracion/modelos-proveedores
    await page.goto('/administracion/modelos-proveedores');
    await waitForAppMounted(page);

    // 3. Locate the deepseek-chat row and wait for initial state binding
    const modelRow = page.locator('tr', { hasText: 'deepseek-chat' }).first();
    await expect(modelRow).toBeVisible({ timeout: 10000 });

    const toggleLabel = modelRow.locator('label', { hasText: /Habilitado|Deshabilitado/ });
    await expect(toggleLabel).toBeVisible();

    const checkbox = toggleLabel.locator('input[type="checkbox"]');
    await expect(checkbox).toBeVisible();

    // 4. Trigger toggle action which encounters the intercepted 500 error
    await checkbox.click();

    // 5. Verify that an observable error alert is rendered in the DOM
    const errorAlert = page.getByRole('alert');
    await expect(errorAlert).toBeVisible({ timeout: 10000 });
    await expect(errorAlert).toContainText('No se pudo cambiar deepseek-chat');

    // 6. Confirm that the Angular app shell remains fully functional and responsive (no white screen)
    await expect(page.locator('app-root')).toBeVisible();
    await expect(page.locator('header')).toBeVisible();

    // 7. Confirm navigation is still responsive despite the handled failure
    const adminHeading = page.getByRole('heading', { name: /Administración \/ Modelos & Proveedores/i });
    await expect(adminHeading).toBeVisible();
  });
});
