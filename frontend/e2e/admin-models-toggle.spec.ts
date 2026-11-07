import { test, expect } from '@playwright/test';
import { resetModelEnablement, setupAuthSession, waitForAppMounted, TEST_MODEL_ID } from './helpers';

test.describe('Provider Model Administration Toggle', () => {
  test.beforeEach(async ({ context, request }) => {
    await setupAuthSession(context);
    await resetModelEnablement(request, TEST_MODEL_ID);
  });

  test.afterEach(async ({ request }) => {
    await resetModelEnablement(request, TEST_MODEL_ID);
  });

  test('navigates to model admin, toggles model enablement, and confirms UI update', async ({ page }) => {
    // 1. Navigate to /administracion/modelos-proveedores
    await page.goto('/administracion/modelos-proveedores');
    await waitForAppMounted(page);

    // 2. Locate the row for deepseek-chat
    const modelRow = page.locator('tr', { hasText: 'deepseek-chat' }).first();
    await expect(modelRow).toBeVisible({ timeout: 10000 });

    // 3. Locate the toggle switch / checkbox inside the row
    const toggleLabel = modelRow.locator('label', { hasText: /Habilitado|Deshabilitado/ });
    await expect(toggleLabel).toBeVisible();

    const checkbox = toggleLabel.locator('input[type="checkbox"]');
    await expect(checkbox).toBeVisible();

    // Verify initial state is checked/Habilitado
    await expect(checkbox).toBeChecked();
    await expect(toggleLabel).toContainText('Habilitado');

    // 4. Toggle the switch off (disable model)
    await checkbox.click();

    // 5. Verify reactive DOM update and success message without full page reload
    await expect(checkbox).not.toBeChecked({ timeout: 10000 });
    await expect(toggleLabel).toContainText('Deshabilitado');

    const successNotice = page.getByRole('status').filter({ hasText: /estado guardado en el servidor/i });
    await expect(successNotice).toBeVisible();

    // 6. Toggle back on to restore state and verify reactive update
    await checkbox.click();
    await expect(checkbox).toBeChecked({ timeout: 10000 });
    await expect(toggleLabel).toContainText('Habilitado');
  });
});
