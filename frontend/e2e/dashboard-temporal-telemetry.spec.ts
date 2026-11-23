import { expect, test } from '@playwright/test';
import { setupAuthSession, waitForAppMounted, E2E_SESSION_TOKEN } from './helpers';

test.use({
  serviceWorkers: 'block',
  extraHTTPHeaders: {
    Authorization: 'Bearer ' + (process.env['MINIME_E2E_AUTH_TOKEN'] || E2E_SESSION_TOKEN),
  },
});

test('renders the real temporal projection and preserves active work', async ({ context, page }) => {
  await setupAuthSession(context, process.env['MINIME_E2E_AUTH_TOKEN'] || E2E_SESSION_TOKEN);
  const projectsResponse = await page.request.get('/api/v1/projects');
  expect(projectsResponse.ok()).toBe(true);
  const projects = await projectsResponse.json() as Array<{ project_id: string }>;
  expect(projects.length).toBeGreaterThan(0);
  await page.addInitScript((id: string) => localStorage.setItem('minime_selected_project_id', id), projects[0].project_id);

  const overviewResponse = page.waitForResponse(response => response.url().includes('/api/v1/dashboard/overview'));
  await page.goto('/dashboard');
  await waitForAppMounted(page);
  const response = await overviewResponse;
  expect(response.status()).toBe(200);
  const payload = await response.json() as { temporal_telemetry: Record<string, { axis: string[]; series: Array<{ series_id: string }> }> };
  expect(Object.keys(payload.temporal_telemetry)).toEqual(expect.arrayContaining(['autonomy', 'time', 'cost']));
  expect(payload.temporal_telemetry.autonomy.series[0].series_id).toBe('global');
  expect(payload.temporal_telemetry.autonomy.axis.length).toBeGreaterThan(0);

  await expect(page.getByTestId('temporal-telemetry-chart')).toBeVisible();
  await page.getByRole('button', { name: '2. Tiempos de Entrega' }).click();
  await page.getByRole('button', { name: '3. Costo liquidado (USD)' }).click();
  await expect(page.getByRole('button', { name: /Restaurar/ })).toBeVisible();
  const global = page.getByRole('button', { name: /Mostrar u ocultar Global/ });
  if (await global.count()) {
    await global.hover();
    await global.click();
    await page.getByRole('button', { name: /Aislar/ }).first().click();
    await page.getByRole('button', { name: /Restaurar/ }).click();
  }
  await expect(page.getByTestId('active-change-card')).toBeVisible();
});
