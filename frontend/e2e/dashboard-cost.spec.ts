import { expect, test } from '@playwright/test';
import { setupAuthSession, waitForAppMounted, E2E_SESSION_TOKEN } from './helpers';

test.use({
  serviceWorkers: 'block',
  extraHTTPHeaders: {
    Authorization: "Bearer " + (process.env['MINIME_E2E_AUTH_TOKEN'] || E2E_SESSION_TOKEN),
  },
});

type Project = { project_id: string; name: string; status: string };

async function selectRealProject(page: import('@playwright/test').Page, projectId?: string) {
  const response = await page.request.get('/api/v1/projects');
  expect(response.ok()).toBe(true);
  const projects = (await response.json()) as Project[];
  const project = projects.find(candidate => candidate.project_id === projectId) ?? projects[0];
  expect(project, 'the isolated PostgreSQL fixture must contain a project').toBeTruthy();
  await page.addInitScript((id: string) => localStorage.setItem('minime_selected_project_id', id), project!.project_id);
  return project!;
}

test('renders the committed ledger projection and preserves provider/model attribution', async ({ context, page }) => {
  await setupAuthSession(context, process.env['MINIME_E2E_AUTH_TOKEN'] || E2E_SESSION_TOKEN);
  await page.route('**/requests', route => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
  await page.route('**/api/v1/providers/quotas', route => route.fulfill({ status: 200, contentType: 'application/json', body: '{"providers":[]}' }));
  const project = await selectRealProject(page, process.env['MINIME_E2E_PROJECT_ID']);
  const response = page.waitForResponse(response => response.url().includes('/api/v1/dashboard/overview'));
  await page.goto('/dashboard');
  await waitForAppMounted(page);
  const dashboardResponse = await response;
  expect(dashboardResponse.status()).toBe(200);
  const payload = (await dashboardResponse.json()) as { cost: { status: string; providers: Array<{ provider: string; models: Array<{ model: string }> }> } };
  expect(payload.cost.status).toBe('available');
  expect(payload.cost.providers.map(provider => provider.provider)).toEqual(expect.arrayContaining(['deepseek_direct', 'openrouter']));
  expect(project.project_id).toBeTruthy();
  await page.getByRole('button', { name: '3. Costo liquidado (USD)' }).click();
  await expect(page.getByText('DeepSeek Direct', { exact: true })).toBeVisible();
  const costCards = page.getByLabel('Costos liquidados por proveedor');
  await expect(costCards.getByText('OpenRouter', { exact: true })).toBeVisible();
  for (const provider of payload.cost.providers) {
    for (const model of provider.models) {
      await expect(page.getByText(model.model, { exact: true })).toBeVisible();
    }
  }
});

test('renders an explicit no-data state without synthetic attribution', async ({ context, page }) => {
  await setupAuthSession(context, process.env['MINIME_E2E_AUTH_TOKEN'] || E2E_SESSION_TOKEN);
  const emptyProjectId = 'dashboard-cost-empty-' + Date.now();
  await page.addInitScript((projectId: string) => localStorage.setItem('minime_selected_project_id', projectId), emptyProjectId);
  await page.goto('/dashboard');
  await waitForAppMounted(page);
  await page.getByRole('button', { name: '3. Costo liquidado (USD)' }).click();
  await expect(page.getByText('Sin datos de costo liquidado', { exact: true })).toBeVisible();
  await expect(page.getByText('No existe un importe verificable en el ledger.', { exact: true })).toBeVisible();
  await expect(page.getByText('CLI', { exact: true })).toHaveCount(0);
});
