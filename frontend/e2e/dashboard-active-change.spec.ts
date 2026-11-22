import { expect, test } from '@playwright/test';

test.use({ serviceWorkers: 'block' });

const project = { project_id: 'e2e-project', name: 'E2E Project', status: 'ACTIVE' };
const activeRun = (stage: string, requestId: string | null = 'request-463') => ({
  run_id: 'run-463-dashboard',
  project_id: project.project_id,
  request_id: requestId,
  change_name: 'issue-463-active-change-dashboard',
  stage,
  status: 'RUNNING',
  is_active: true,
});

async function stubDashboardApi(
  page: import('@playwright/test').Page,
  options: { stage?: string; requestId?: string | null; includeRequest?: boolean; includeRun?: boolean } = {},
) {
  const {
    stage = 'IMPLEMENTING',
    requestId = 'request-463',
    includeRequest = true,
    includeRun = true,
  } = options;

  await page.addInitScript((projectId: string) => localStorage.setItem('minime_selected_project_id', projectId), project.project_id);
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    let body: unknown = [];
    if (url.pathname === '/api/v1/auth/me') body = { authenticated: true, user: { email: 'e2e@example.com', name: 'E2E' } };
    else if (url.pathname === '/api/v1/projects') body = [project];
    else if (url.pathname === '/api/v1/orchestration/runs') body = includeRun ? [activeRun(stage, requestId)] : [];
    else if (url.pathname.endsWith('/requests')) {
      body = includeRequest
        ? [{ request_id: 'request-463', project_id: project.project_id, issue_number: 463, title: 'Tarjeta compacta del Change activo', status: 'IN_PROGRESS' }]
        : [];
    } else if (url.pathname === '/api/v1/dashboard/overview') body = { cost: { status: 'no_data', providers: [], series: [] } };
    else if (url.pathname === '/api/v1/providers/quotas') body = { providers: [] };
    else if (url.pathname === '/api/v1/events') return route.abort();
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
}

test.describe('Dashboard active Change summary', () => {
  for (const [viewportName, viewport] of Object.entries({
    desktop: { width: 1440, height: 900 },
    tablet: { width: 768, height: 1024 },
    mobile: { width: 360, height: 800 },
  })) {
    test(`${viewportName} shows the active Change and stage without requiring a gate`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await stubDashboardApi(page);
      await page.goto('/dashboard');

      const card = page.getByTestId('active-change-card');
      await expect(card).toBeVisible();
      await expect(page.getByTestId('active-change-name')).toHaveText('issue-463-active-change-dashboard');
      await expect(page.getByTestId('active-change-request')).toContainText('#463');
      await expect(page.getByTestId('active-change-request')).toContainText('Tarjeta compacta del Change activo');
      await expect(page.getByTestId('active-change-stage')).toContainText('Implementación');
      await expect(page.getByTestId('active-change-status')).toHaveText('RUNNING');
      await expect(page.getByTestId('active-change-illustration')).toHaveAttribute('src', '/illustrations/implementing.png');
      await expect(page.getByTestId('active-change-stage-progress').getByRole('listitem')).toHaveCount(10);
      await expect(page.getByText('Runs de Orquestación', { exact: true })).toHaveCount(0);
      await expect(page.getByText('Solicitudes de Cambio', { exact: true })).toHaveCount(0);
      await expect(page.getByTestId('active-change-link')).toHaveAttribute('href', /trabajo-actual\?run=run-463-dashboard&project=e2e-project/);
      expect(await page.locator('html').evaluate(element => element.scrollWidth)).toBeLessThanOrEqual(viewport.width);
    });
  }

  test('omits Request information when the referenced Request is unavailable', async ({ page }) => {
    await stubDashboardApi(page, { includeRequest: false });
    await page.goto('/dashboard');

    await expect(page.getByTestId('active-change-name')).toBeVisible();
    await expect(page.getByTestId('active-change-request')).toHaveCount(0);
  });

  test('shows a useful idle state with a Backlog link when there is no active Run', async ({ page }) => {
    await stubDashboardApi(page, { includeRun: false });
    await page.goto('/dashboard');

    await expect(page.getByTestId('active-change-idle')).toHaveText('Sin ejecución activa en este momento');
    await expect(page.getByTestId('active-change-backlog-link')).toHaveAttribute('href', '/backlog');
    await expect(page.getByTestId('active-change-illustration')).toHaveCount(0);
  });

  test('does not guess an illustration or progress for an unknown stage', async ({ page }) => {
    await stubDashboardApi(page, { stage: 'FUTURE_STAGE' });
    await page.goto('/dashboard');

    await expect(page.getByTestId('active-change-stage')).toContainText('FUTURE_STAGE');
    await expect(page.getByTestId('active-change-illustration')).toHaveCount(0);
    await expect(page.getByTestId('active-change-stage-progress')).toHaveCount(0);
  });

  test('opens Trabajo Actual for the same Run', async ({ page }) => {
    await stubDashboardApi(page);
    await page.goto('/dashboard');
    await page.getByTestId('active-change-link').click();

    await expect(page).toHaveURL(/\/trabajo-actual\?run=run-463-dashboard&project=e2e-project/);
    await expect(page.getByTestId('stage-illustration')).toHaveAttribute('src', '/illustrations/implementing.png');
  });
});
