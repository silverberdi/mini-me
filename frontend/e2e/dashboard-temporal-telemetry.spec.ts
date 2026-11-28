import { expect, test } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import { setupAuthSession, waitForAppMounted, E2E_SESSION_TOKEN } from './helpers';

const fixtureSuffix = `${Date.now()}-${process.pid}`;
const fixtureScript = resolve(process.cwd(), '../tests/telemetry_dashboard_fixture.py');

function runFixture(action: 'seed' | 'cleanup'): void {
  execFileSync(process.env['PYTHON'] || 'python3', [fixtureScript, action, fixtureSuffix], {
    cwd: resolve(process.cwd(), '..'), env: process.env, stdio: 'pipe',
  });
}

test.use({
  serviceWorkers: 'block',
  extraHTTPHeaders: {
    Authorization: 'Bearer ' + (process.env['MINIME_E2E_AUTH_TOKEN'] || E2E_SESSION_TOKEN),
  },
});

test('renders the real temporal projection and preserves active work', async ({ context, page }) => {
  runFixture('seed');
  try {
  await setupAuthSession(context, process.env['MINIME_E2E_AUTH_TOKEN'] || E2E_SESSION_TOKEN);
  const projectsResponse = await page.request.get('/api/v1/projects');
  expect(projectsResponse.ok()).toBe(true);
  const projects = await projectsResponse.json() as Array<{ project_id: string }>;
  expect(projects.length).toBeGreaterThan(0);
  const selectedProject = projects.find(project => project.project_id === 'e2e-project') || projects[0];
  await page.addInitScript((id: string) => localStorage.setItem('minime_selected_project_id', id), selectedProject.project_id);

  const overviewResponse = page.waitForResponse(response => response.url().includes('/api/v1/dashboard/overview'));
  await page.goto('/dashboard');
  await waitForAppMounted(page);
  const response = await overviewResponse;
  expect(response.status()).toBe(200);
  const payload = await response.json() as { temporal_telemetry: Record<string, { axis: string[]; series: Array<{ series_id: string; points?: Array<{ autonomy_outcomes?: Record<string, number> }> }> }> };
  expect(Object.keys(payload.temporal_telemetry)).toEqual(expect.arrayContaining(['autonomy', 'time', 'cost']));
  expect(payload.temporal_telemetry.autonomy.series[0].series_id).toBe('global');
  expect(payload.temporal_telemetry.autonomy.axis.length).toBeGreaterThan(0);
  expect(payload.temporal_telemetry.autonomy.series.flatMap(series => series.points || []).every(point => point.autonomy_outcomes !== undefined)).toBe(true);
  const points = payload.temporal_telemetry.autonomy.series.flatMap(series => series.points || []);
  expect(points.some(point => (point.autonomy_outcomes?.['governance_authorization'] || 0) > 0)).toBe(true);
  expect(points.some(point => point.autonomy_outcomes && Object.values(point.autonomy_outcomes).some(value => value > 0))).toBe(true);

  await expect(page.getByTestId('temporal-telemetry-chart')).toBeVisible();
  await expect(page.getByTestId('autonomy-outcome-summary')).toBeVisible();
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
  } finally {
    runFixture('cleanup');
  }
});

test('renders explicit no-data for a real project without eligible stage evidence', async ({ context, page }) => {
  runFixture('seed');
  try {
    await setupAuthSession(context, process.env['MINIME_E2E_AUTH_TOKEN'] || E2E_SESSION_TOKEN);
    const projectsResponse = await page.request.get('/api/v1/projects');
    expect(projectsResponse.ok()).toBe(true);
    const projects = await projectsResponse.json() as Array<{ project_id: string }>;
    const emptyProject = projects.find(project => project.project_id.startsWith('telemetry-empty-'));
    expect(emptyProject).toBeDefined();
    await page.addInitScript((id: string) => localStorage.setItem('minime_selected_project_id', id), emptyProject!.project_id);
    await page.route('**/api/v1/dashboard/overview', async route => {
      const response = await route.fetch();
      const payload = await response.json();
      payload.temporal_telemetry.autonomy = {
        ...payload.temporal_telemetry.autonomy,
        no_data: true,
        series: payload.temporal_telemetry.autonomy.series.map((series: Record<string, unknown>) => ({ ...series, points: [], no_data: true })),
      };
      await route.fulfill({ response, json: payload });
    });
    await page.goto('/dashboard');
    await waitForAppMounted(page);
    await expect(page.getByText('Sin datos verificables para esta dimensión', { exact: true })).toBeVisible();
  } finally {
    runFixture('cleanup');
  }
});
