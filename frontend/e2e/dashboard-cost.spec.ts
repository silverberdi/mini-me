import { expect, test } from '@playwright/test';

test.use({ serviceWorkers: 'block' });

const project = { project_id: 'cost-e2e-project', name: 'Cost E2E', status: 'ACTIVE' };
const availableCost = {
  status: 'available',
  providers: [
    {
      provider: 'deepseek_direct',
      label: 'DeepSeek Direct',
      amount_usd: '0.123456',
      models: [{ model: 'deepseek/deepseek-flash', amount_usd: '0.123456' }],
    },
    {
      provider: 'openrouter',
      label: 'OpenRouter',
      amount_usd: '1.220000',
      models: [{ model: 'openrouter/deepseek/deepseek-r1', amount_usd: '1.220000' }],
    },
  ],
  series: [
    {
      day: '2026-11-23',
      provider: 'deepseek_direct',
      model: 'deepseek/deepseek-flash',
      amount_usd: '0.123456',
      source_timestamps: ['2026-11-23T12:00:00+00:00'],
    },
    {
      day: '2026-11-23',
      provider: 'openrouter',
      model: 'openrouter/deepseek/deepseek-r1',
      amount_usd: '1.220000',
      source_timestamps: ['2026-11-23T12:01:00+00:00'],
    },
  ],
};

async function stubDashboard(page: import('@playwright/test').Page, cost: unknown) {
  await page.addInitScript((projectId: string) => localStorage.setItem('minime_selected_project_id', projectId), project.project_id);
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    let body: unknown = [];
    if (url.pathname === '/api/v1/auth/me') body = { authenticated: true, user: { email: 'e2e@example.com', name: 'E2E' } };
    else if (url.pathname === '/api/v1/projects') body = [project];
    else if (url.pathname === '/api/v1/orchestration/runs') body = [];
    else if (url.pathname === '/api/v1/dashboard/overview') body = { cost };
    else if (url.pathname === '/api/v1/providers/quotas') body = { providers: [] };
    else if (url.pathname === '/api/v1/events') return route.abort();
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
}

test('renders the committed ledger projection and preserves provider/model attribution', async ({ page }) => {
  await stubDashboard(page, availableCost);
  const response = page.waitForResponse(response => response.url().includes('/api/v1/dashboard/overview'));
  await page.goto('/dashboard');
  await expect((await response).status()).toBe(200);
  await page.getByRole('button', { name: '3. Costo liquidado (USD)' }).click();
  await expect(page.getByText('DeepSeek Direct', { exact: true })).toBeVisible();
  const costCards = page.getByLabel('Costos liquidados por');
  await expect(costCards.getByText('OpenRouter', { exact: true })).toBeVisible();
  await expect(page.getByText('deepseek/deepseek-flash', { exact: true })).toBeVisible();
  await expect(page.getByText('openrouter/deepseek/deepseek-r1', { exact: true })).toBeVisible();
  await expect(costCards.getByText('$0.123456', { exact: true })).toBeVisible();
  await expect(costCards.getByText('$1.220000', { exact: true })).toBeVisible();
});

test('renders an explicit no-data state without synthetic attribution', async ({ page }) => {
  await stubDashboard(page, { status: 'no_data', providers: [], series: [] });
  await page.goto('/dashboard');
  await page.getByRole('button', { name: '3. Costo liquidado (USD)' }).click();
  await expect(page.getByText('Sin datos de costo liquidado', { exact: true })).toBeVisible();
  await expect(page.getByText('No existe un importe verificable en el ledger.', { exact: true })).toBeVisible();
  await expect(page.getByText('CLI', { exact: true })).toHaveCount(0);
});
