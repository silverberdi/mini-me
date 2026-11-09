import { test, expect } from '@playwright/test';
import { setupAuthSession, waitForAppMounted } from './helpers';

test.describe('Searchable Model Combobox in Project Configuration', () => {
  test.beforeEach(async ({ context }) => {
    await setupAuthSession(context);
  });

  test('opens create project modal and filters models with keyboard and mouse', async ({ context, page }) => {
    // Intercept auth session, projects and agent catalog with deterministic test data at context level
    await context.route('**/api/v1/auth/me', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          authenticated: true,
          user: { email: 'e2e@example.com', name: 'E2E User' },
        }),
      });
    });

    await context.route('**/api/v1/projects', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            project_id: 'e2e-project',
            display_name: 'E2E Test Project',
            status: 'ACTIVE',
            repository: 'https://github.com/test/repo',
            base_branch: 'main',
            agent_profiles: {
              thinking: { model_id: 'claude-sonnet-5-5-medium', effort: 'medium' },
              execution: { model_id: 'claude-sonnet-5-5-medium', effort: 'medium' },
              independent_review: { model_id: 'claude-sonnet-5-5-medium', effort: 'medium' },
              fallback: { model_id: 'claude-sonnet-5-5-medium', effort: 'medium' },
            },
          },
        ]),
      });
    });

    await context.route('**/api/v1/catalogs/agents*', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          agents: [
            {
              id: 'antigravity',
              capability_status: 'OBSERVED_READ_ONLY',
              models: {
                'claude-sonnet-5-5-low': ['low'],
                'claude-sonnet-5-5-medium': ['medium'],
                'claude-sonnet-5-5-high': ['high'],
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

    // 7. Verify options filter, ensure no duplicated options (exactly 1 Claude Sonnet), and select
    const claudeSonnetOptions = page.getByRole('option').filter({ hasText: /Claude SONNET/i });
    await expect(claudeSonnetOptions).toHaveCount(1);
    await claudeSonnetOptions.first().click();

    // 8. Verify combobox closes and displays chosen model
    await expect(thinkingCombobox).toHaveAttribute('aria-expanded', 'false');
    await expect(thinkingCombobox).toContainText('Claude');

    // 9. Verify independent effort radio buttons are present and interactive
    const effortRadios = page.locator('input[name="new_effort_thinking"]');
    await expect(effortRadios).toHaveCount(3);
    const highEffortRadio = page.locator('input[name="new_effort_thinking"][value="high"]');
    await highEffortRadio.check();
    await expect(highEffortRadio).toBeChecked();
  });

  test('renders error message inside create modal when submission fails without closing modal', async ({ context, page }) => {
    await context.route('**/api/v1/auth/me', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          authenticated: true,
          user: { email: 'e2e@example.com', name: 'E2E User' },
        }),
      });
    });

    await context.route('**/api/v1/projects', async route => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 400,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Error al registrar proyecto: Canonical provider and harness are required for every role: thinking' }),
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([
            {
              project_id: 'e2e-project',
              display_name: 'E2E Test Project',
              status: 'ACTIVE',
              repository: 'https://github.com/test/repo',
              base_branch: 'main',
              agent_profiles: {
                thinking: { model_id: 'gpt-5.6-luna', effort: 'medium' },
                execution: { model_id: 'gpt-5.6-luna', effort: 'medium' },
                independent_review: { model_id: 'claude-sonnet-5-5-medium', effort: 'medium' },
                fallback: { model_id: 'gpt-5.6-luna', effort: 'medium' },
              },
            },
          ]),
        });
      }
    });

    await context.route('**/api/v1/catalogs/agents*', async route => {
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
              },
              model_routes: {},
            },
            {
              id: 'codex',
              capability_status: 'OBSERVED_READ_ONLY',
              models: {
                'gpt-5.6-luna': ['medium'],
              },
              model_routes: {},
            },
          ],
        }),
      });
    });

    await page.goto('/proyectos');
    await waitForAppMounted(page);

    const newProjectBtn = page.getByRole('button', { name: /\+.*Nuevo Proyecto/i });
    await expect(newProjectBtn).toBeVisible({ timeout: 10000 });
    await newProjectBtn.click();

    const modalHeading = page.getByRole('heading', { name: /Nuevo Proyecto/i });
    await expect(modalHeading).toBeVisible();

    await page.locator('input[name="project_id"]').fill('test-proj');
    await page.locator('input[name="display_name"]').fill('Test Project');
    await page.locator('input[name="repository"]').fill('https://github.com/test/repo');

    const submitBtn = page.getByRole('button', { name: /Crear Proyecto/i });
    await expect(submitBtn).toBeEnabled();
    await submitBtn.click();

    const modalAlert = page.locator('div.fixed.inset-0').getByRole('alert');
    await expect(modalAlert).toBeVisible();
    await expect(modalAlert).toContainText('Error al registrar proyecto');
    await expect(modalHeading).toBeVisible();
  });
});
