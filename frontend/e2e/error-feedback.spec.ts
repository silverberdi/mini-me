import { test, expect } from '@playwright/test';
import { setupAuthSession, waitForAppMounted } from './helpers';

test.describe('Observable Error Feedback and Runtime Resilience', () => {
  test('displays observable error notification upon API failure without crashing Angular shell', async ({ context, page }) => {
    await setupAuthSession(context);
    // 1. Navigate to /administracion/modelos-proveedores
    await page.goto('/administracion/modelos-proveedores');
    await waitForAppMounted(page);

    // 2. Intercept model toggle endpoint to simulate a server 500 error
    await page.route('**/api/v1/admin/providers/models/*/enabled', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Error de servidor simulado para prueba E2E' }),
      });
    });

    // 3. Trigger model toggle on the deepseek-chat row
    const modelRow = page.locator('tr', { hasText: 'deepseek-chat' }).first();
    await expect(modelRow).toBeVisible({ timeout: 10000 });

    const checkbox = modelRow.locator('input[type="checkbox"]');
    await expect(checkbox).toBeVisible();
    await checkbox.click();

    // 4. Verify that an observable error alert is rendered in the DOM
    const errorAlert = page.getByRole('alert');
    await expect(errorAlert).toBeVisible({ timeout: 5000 });
    await expect(errorAlert).toContainText('No se pudo cambiar deepseek-chat');

    // 5. Confirm that the Angular app shell remains fully functional and responsive (no white screen)
    await expect(page.locator('app-root')).toBeVisible();
    await expect(page.locator('header')).toBeVisible();

    // 6. Confirm navigation is still responsive despite the handled failure
    const adminHeading = page.getByRole('heading', { name: /Administración \/ Modelos & Proveedores/i });
    await expect(adminHeading).toBeVisible();
  });
});
