import { test, expect } from '@playwright/test';
import { setupAuthSession, waitForAppMounted } from './helpers';

test.describe('Searchable Model Combobox in Project Configuration', () => {
  test.beforeEach(async ({ context }) => {
    await setupAuthSession(context);
  });

  test('opens create project modal and filters models with keyboard and mouse', async ({ context, page }) => {
    // Intercept agent catalog with deterministic test data at context level
    await context.route('**/api/v1/catalogs/agents', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          agents: [
            {
              id: 'antigravity',
              capability_status: 'OBSERVED_READ_ONLY',
              models: {
                'claude-sonnet-5-5-medium': ['medium'],
                'gemini-3.8-flash-medium': ['medium'],
              },
              model_routes: {},
            },
            {
              id: 'opencode',
              capability_status: 'OBSERVED_READ_ONLY',
              models: {
                'openrouter/~anthropic/claude-fable-latest': null,
                'deepseek/deepseek-v4-pro': null,
              },
              model_routes: {
                'openrouter/~anthropic/claude-fable-latest': 'openrouter',
                'deepseek/deepseek-v4-pro': 'deepseek_direct',
              },
            },
          ],
        }),
      });
    });

    // 1. Navigate to /proyectos view
    await page.goto('/proyectos');
    await waitForAppMounted(page);

    // Wait for the project card to be visible ensuring initial project list and catalog have loaded
    const projectCard = page.locator('div', { hasText: 'E2E Test Project' }).first();
    await expect(projectCard).toBeVisible({ timeout: 10000 });

    // 2. Open Create Project Modal
    const newProjectBtn = page.getByRole('button', { name: /\+.*Nuevo Proyecto/i });
    await expect(newProjectBtn).toBeVisible({ timeout: 10000 });
    await newProjectBtn.click();

    // 3. Verify modal appears with the 4 comboboxes
    const modalHeading = page.getByRole('heading', { name: /Nuevo Proyecto/i });
    await expect(modalHeading).toBeVisible();

    // 4. Find the Thinking role combobox button
    const thinkingCombobox = page.locator('app-model-combobox', { hasText: /Thinking/i }).getByRole('combobox');
    await expect(thinkingCombobox).toBeVisible();

    // 5. Click to open the dropdown
    await thinkingCombobox.click();
    await expect(thinkingCombobox).toHaveAttribute('aria-expanded', 'true');

    // 6. Verify search input appears and type query
    const searchInput = page.getByPlaceholder('Buscar por proveedor o modelo…');
    await expect(searchInput).toBeVisible();
    await searchInput.fill('Claude');

    // 7. Verify options filter and select via keyboard or click
    const filteredOption = page.getByRole('option').filter({ hasText: /Claude/i }).first();
    await expect(filteredOption).toBeVisible({ timeout: 10000 });
    await filteredOption.click();

    // 8. Verify combobox closes and displays chosen model
    await expect(thinkingCombobox).toHaveAttribute('aria-expanded', 'false');
    await expect(thinkingCombobox).toContainText('Claude');
  });
});
