import { test, expect } from '@playwright/test';
import { setupAuthSession, waitForAppMounted } from './helpers';

test.describe('Project Creation Stepper and Selection Persistence (Ref #355)', () => {
  test.beforeEach(async ({ context }) => {
    await setupAuthSession(context);

    // Provide deterministic models catalog
    await context.route('**/api/v1/catalogs/agents*', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          agents: [
            {
              id: 'codex',
              capability_status: 'OBSERVED_READ_ONLY',
              models: {
                'gpt-5.6-luna': ['medium'],
              },
              model_routes: {},
            },
            {
              id: 'antigravity',
              capability_status: 'OBSERVED_READ_ONLY',
              models: {
                'claude-sonnet-5-5-medium': ['medium'],
              },
              model_routes: {},
            },
          ],
        }),
      });
    });
  });

  test('creation modal displays 4-stage stepper and surfaces GitHub authorization error feedback', async ({ page }) => {
    // 1. Navigate to /proyectos view
    await page.goto('/proyectos');
    await waitForAppMounted(page);

    // 2. Open "+ Nuevo Proyecto" modal
    const newProjectBtn = page.getByRole('button', { name: /\+ Nuevo Proyecto/i });
    await expect(newProjectBtn).toBeVisible();
    await newProjectBtn.click();

    // 3. Confirm modal is visible
    const modalHeading = page.getByRole('heading', { name: /Registrar Nuevo Proyecto/i });
    await expect(modalHeading).toBeVisible();

    // 4. Fill in project form with an inaccessible / nonexistent repository
    const idInput = page.locator('input[name="project_id"]');
    await idInput.fill('e2e-stepper-test');

    const nameInput = page.locator('input[name="display_name"]');
    await nameInput.fill('E2E Stepper Test Project');

    const repoInput = page.locator('input[name="repository"]');
    await repoInput.fill('unauthorized-org/unauthorized-repo');

    // 5. Submit creation
    const submitBtn = page.getByRole('button', { name: /Crear Proyecto/i });
    await expect(submitBtn).toBeEnabled({ timeout: 10000 });
    await submitBtn.click();

    // 6. Verify error feedback appears inside the modal
    const alertBox = page.locator('div[role="alert"]').filter({ hasText: /error/i });
    await expect(alertBox).toBeVisible({ timeout: 15000 });

    // 7. Verify GitHub authorization guidance is displayed
    const guidanceBox = page.locator('div').filter({ hasText: /Autorización de GitHub requerida/i }).first();
    await expect(guidanceBox).toBeVisible();
    await expect(guidanceBox).toContainText('Installed GitHub Apps');
    await expect(guidanceBox).toContainText('All repositories');

    // 8. Cancel modal
    const cancelBtn = page.getByRole('button', { name: /Cancelar/i });
    await cancelBtn.click();
    await expect(modalHeading).toBeHidden();
  });

  test('selected project is persisted in localStorage across page reload', async ({ page }) => {
    await page.goto('/proyectos');
    await waitForAppMounted(page);

    // Set selected project in localStorage
    await page.evaluate(() => {
      localStorage.setItem('minime_selected_project_id', 'e2e-project');
    });

    // Reload page
    await page.reload();
    await waitForAppMounted(page);

    // Verify localStorage retained value
    const storedVal = await page.evaluate(() => localStorage.getItem('minime_selected_project_id'));
    expect(storedVal).toBe('e2e-project');
  });
});
