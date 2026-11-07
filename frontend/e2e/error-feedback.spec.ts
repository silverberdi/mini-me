import { test, expect } from '@playwright/test';
import { resetProjectState, setupAuthSession, waitForAppMounted, TEST_PROJECT_ID } from './helpers';

test.describe('Observable Error Feedback and Runtime Resilience', () => {
  test.beforeEach(async ({ request }) => {
    await resetProjectState(request, TEST_PROJECT_ID);
  });

  test.afterEach(async ({ request }) => {
    await resetProjectState(request, TEST_PROJECT_ID);
  });

  test('displays observable error notification upon API failure without crashing Angular shell', async ({ context, page }) => {
    // 1. Setup authenticated session
    await setupAuthSession(context);

    // 2. Intercept project pause endpoint at browser context level to simulate server 500 failure
    await context.route('**/api/v1/projects/*/pause', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Error de servidor simulado para prueba E2E' }),
      });
    });

    // 3. Navigate to /proyectos view
    await page.goto('/proyectos');
    await waitForAppMounted(page);

    // 4. Select project card and locate pause button
    const projectCard = page.locator('div', { hasText: 'E2E Test Project' }).first();
    await expect(projectCard).toBeVisible({ timeout: 10000 });
    await projectCard.click();

    const pauseButton = page.getByRole('button', { name: /⏸ Pausar|▶ Reanudar/i });
    await expect(pauseButton).toBeVisible();
    await expect(pauseButton).toContainText('Pausar');

    // 5. Trigger action which encounters the intercepted 500 error
    await pauseButton.click();

    // 6. Verify observable error message in the DOM
    const errorNotice = page.locator('div', { hasText: /Error:/i }).first();
    await expect(errorNotice).toBeVisible({ timeout: 10000 });
    await expect(errorNotice).toContainText('Error de servidor simulado para prueba E2E');

    // 7. Confirm that the Angular app shell remains fully functional and responsive (no white screen)
    await expect(page.locator('app-root')).toBeVisible();
    await expect(page.locator('header')).toBeVisible();

    // 8. Confirm page heading is intact and responsive
    await expect(page.getByRole('heading', { name: /Proyectos Administrados/i })).toBeVisible();
  });
});
