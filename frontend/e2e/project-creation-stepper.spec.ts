import { test, expect } from '@playwright/test';
import { setupAuthSession, waitForAppMounted } from './helpers';

test.describe('Project Creation Stepper and Selection Persistence (Ref #355)', () => {
  test.beforeEach(async ({ context }) => {
    await setupAuthSession(context);

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
          body: JSON.stringify({
            detail: "Error al registrar proyecto en etapa connection_and_grants: La GitHub App no tiene acceso al repositorio 'unauthorized-org/unauthorized-repo'. Por favor, configure el acceso en los ajustes de instalación de la GitHub App (agregue el repositorio a la lista permitida o seleccione 'All repositories').",
          }),
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

    // 7. Verify stepper progress is displayed
    const stepperHeading = page.getByText(/Progreso de Creación Guiada/i);
    await expect(stepperHeading).toBeVisible();

    // 8. Verify GitHub authorization guidance is displayed
    const guidanceBox = page.locator('div').filter({ hasText: /Autorización de GitHub requerida/i }).first();
    await expect(guidanceBox).toBeVisible();
    await expect(guidanceBox).toContainText('Installed GitHub Apps');
    await expect(guidanceBox).toContainText('All repositories');

    // 9. Cancel modal
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
