import { test, expect } from '@playwright/test';
import { resetProjectState, setupAuthSession, waitForAppMounted, TEST_PROJECT_ID } from './helpers';

test.describe('Project Pause and Resume Lifecycle', () => {
  test.beforeEach(async ({ context, request }) => {
    await setupAuthSession(context);
    await resetProjectState(request, TEST_PROJECT_ID);
  });

  test.afterEach(async ({ request }) => {
    await resetProjectState(request, TEST_PROJECT_ID);
  });

  test('toggles project pause, verifies reactive UI update, and confirms persistence after reload', async ({ page }) => {
    // 1. Navigate to /proyectos view
    await page.goto('/proyectos');
    await waitForAppMounted(page);

    // 2. Select the E2E project card if not already focused
    const projectCard = page.locator('div', { hasText: 'E2E Test Project' }).first();
    await expect(projectCard).toBeVisible({ timeout: 10000 });
    await projectCard.click();

    // 3. Locate the Pause / Resume button in the active project management panel
    const pauseButton = page.getByRole('button', { name: /⏸ Pausar|▶ Reanudar/i });
    await expect(pauseButton).toBeVisible();

    // If initially active, it should say "⏸ Pausar"
    await expect(pauseButton).toContainText('Pausar');

    // 4. Click to pause the project
    await pauseButton.click();

    // 5. Verify reactive DOM updates without page refresh
    // The button transitions to "▶ Reanudar"
    await expect(pauseButton).toContainText('Reanudar', { timeout: 10000 });

    // The project badge or status reflects PAUSED
    const pausedIndicator = page.getByRole('status').filter({ hasText: /pausado/i }).first();
    await expect(pausedIndicator).toBeVisible();

    // 6. Reload page (F5 simulation) to verify PostgreSQL persistence
    await page.reload();
    await waitForAppMounted(page);

    // 7. Verify the project retains PAUSED state from database
    const pauseButtonAfterReload = page.getByRole('button', { name: /⏸ Pausar|▶ Reanudar/i });
    await expect(pauseButtonAfterReload).toBeVisible();
    await expect(pauseButtonAfterReload).toContainText('Reanudar');

    // 8. Re-activate the project (resume)
    await pauseButtonAfterReload.click();
    await expect(pauseButtonAfterReload).toContainText('Pausar', { timeout: 10000 });
  });
});
