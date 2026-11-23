import { expect, test } from '@playwright/test';

test.use({
  serviceWorkers: 'block',
  extraHTTPHeaders: process.env['MINIME_E2E_AUTH_TOKEN']
    ? { Authorization: `Bearer ${process.env['MINIME_E2E_AUTH_TOKEN']}` }
    : {},
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

test('renders the committed ledger projection and preserves provider/model attribution', async ({ page }) => {
  const project = await selectRealProject(page, process.env['MINIME_E2E_PROJECT_ID']);
  const response = page.waitForResponse(response => response.url().includes('/api/v1/dashboard/overview'));
  await page.goto('/dashboard');
  const dashboardResponse = await response;
  expect(dashboardResponse.status()).toBe(200);
  const payload = (await dashboardResponse.json()) as { cost: { status: string; providers: Array<{ provider: string; models: Array<{ model: string }> }> } };
  expect(payload.cost.status).toBe('available');
  expect(payload.cost.providers.map(provider => provider.provider)).toEqual(expect.arrayContaining(['deepseek_direct', 'openrouter']));
  expect(project.project_id).toBeTruthy();
  await page.getByRole('button', { name: '3. Costo liquidado (USD)' }).click();
  await expect(page.getByText('DeepSeek Direct', { exact: true })).toBeVisible();
  const costCards = page.getByLabel('Costos liquidados por');
  await expect(costCards.getByText('OpenRouter', { exact: true })).toBeVisible();
  for (const provider of payload.cost.providers) {
    for (const model of provider.models) {
      await expect(page.getByText(model.model, { exact: true })).toBeVisible();
    }
  }
});

test('renders an explicit no-data state without synthetic attribution', async ({ page }) => {
  const emptyProjectId = `dashboard-cost-empty-${Date.now()}`;
  await page.addInitScript((projectId: string) => localStorage.setItem('minime_selected_project_id', projectId), emptyProjectId);
  await page.goto('/dashboard');
  await page.getByRole('button', { name: '3. Costo liquidado (USD)' }).click();
  await expect(page.getByText('Sin datos de costo liquidado', { exact: true })).toBeVisible();
  await expect(page.getByText('No existe un importe verificable en el ledger.', { exact: true })).toBeVisible();
  await expect(page.getByText('CLI', { exact: true })).toHaveCount(0);
});
