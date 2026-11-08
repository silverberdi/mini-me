import { test, expect } from '@playwright/test';

test.use({ serviceWorkers: 'block' });

const stages = {
  ADMITTED: '/illustrations/admitted.png',
  EXPLORING: '/illustrations/exploring.png',
  PROPOSING: '/illustrations/proposing.png',
  PROPOSAL_REVIEW: '/illustrations/proposal-review.png',
  IMPLEMENTING: '/illustrations/implementing.png',
  RUNNING_TESTS: '/illustrations/running-tests.png',
  VERIFYING: '/illustrations/verifying.png',
  CODE_REVIEW: '/illustrations/code-review.png',
  PREPARING_PR: '/illustrations/preparing-pr.png',
  COMPLETED: '/illustrations/completed.png',
} as const;

const project = { project_id: 'e2e-project', name: 'E2E Project', status: 'ACTIVE' };
const run = (stage: string) => ({
  run_id: 'run-301-ui', project_id: project.project_id, request_id: 'request-301',
  change_name: 'req-301-pwa-mostrar-la-ilustracion-de-la-etapa-a', stage, status: stage === 'COMPLETED' ? 'SUCCEEDED' : 'RUNNING',
  is_active: stage !== 'COMPLETED', created_at: '2026-11-08T00:00:00Z', updated_at: '2026-11-08T00:00:00Z',
});

async function stubReadOnlyApi(page: import('@playwright/test').Page, getStage: () => string, hasRun = () => true) {
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    let body: unknown = [];
    if (url.pathname === '/api/v1/auth/me') body = { authenticated: true, user: { email: 'e2e@example.com', name: 'E2E' } };
    else if (url.pathname === '/api/v1/projects') body = [project];
    else if (url.pathname === '/api/v1/orchestration/runs') body = hasRun() ? [run(getStage())] : [];
    else if (url.pathname.endsWith('/requests')) body = [];
    else if (url.pathname === '/api/v1/dashboard/overview') body = { cost: { status: 'no_data', providers: [], series: [] } };
    else if (url.pathname === '/api/v1/providers/quotas') body = { providers: [] };
    else if (url.pathname === '/api/v1/events') return route.abort();
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
}

test.describe('Trabajo actual card against the served Angular production build', () => {
  for (const [viewportName, viewport] of Object.entries({
    desktop: { width: 1440, height: 900 }, tablet: { width: 1024, height: 768 },
    mobile: { width: 390, height: 844 }, narrow: { width: 360, height: 800 },
  })) {
    test(`${viewportName} preserves stage illustration and responsive card behavior`, async ({ page }) => {
      await page.setViewportSize(viewport);
      let currentStage: keyof typeof stages = 'RUNNING_TESTS';
      await stubReadOnlyApi(page, () => currentStage);
      await page.goto('/trabajo-actual');

      await expect(page.getByTestId('stage-illustration')).toHaveAttribute('src', stages[currentStage]);
      await expect(page.getByTestId('stage-illustration')).toHaveAttribute('alt', '');
      await expect(page.getByTestId('back-to-work')).toHaveCSS('white-space', 'nowrap');
      await expect(page.getByText('Etapa actual observada:')).toBeVisible();
      expect(await page.locator('body').evaluate(element => element.scrollWidth)).toBeLessThanOrEqual(viewport.width);
      expect(await page.getByTestId('back-to-work').evaluate(element => element.getBoundingClientRect().height)).toBeLessThan(40);

      currentStage = 'CODE_REVIEW';
      await page.reload();
      await expect(page.getByTestId('stage-illustration')).toHaveAttribute('src', stages[currentStage]);
    });
  }

  test('does not render a broken or guessed image for absent or unknown stage', async ({ page }) => {
    let hasRun = false;
    const currentStage = () => 'UNKNOWN';
    await stubReadOnlyApi(page, currentStage, () => hasRun);
    await page.goto('/trabajo-actual');
    await expect(page.getByText('No hay un Run disponible para supervisión')).toBeVisible();
    await expect(page.getByTestId('stage-illustration')).toHaveCount(0);

    hasRun = true;
    await page.reload();
    await expect(page.getByText('Etapa actual observada:')).toBeVisible();
    await expect(page.getByTestId('stage-illustration')).toHaveCount(0);
  });

  test('candidate card is no taller than the previous card at the same viewport and content', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await stubReadOnlyApi(page, () => 'RUNNING_TESTS');
    await page.goto('/trabajo-actual');
    await expect(page.getByTestId('stage-illustration')).toBeVisible();

    const heights = await page.evaluate(() => {
      const candidate = document.querySelector('[data-testid="stage-illustration-slot"]')?.parentElement;
      const baseline = document.createElement('div');
      baseline.className = 'flex flex-col md:flex-row md:items-center justify-between gap-4 bg-slate-800/40 p-6 rounded-2xl border border-slate-700/50 backdrop-blur-sm';
      baseline.innerHTML = '<div><h1 class="text-2xl font-bold tracking-tight text-white">Trabajo Actual</h1><p class="text-sm text-slate-400 mt-1">Supervisión detallada de la ejecución, avance de fases y resolución de atención humana.</p></div><div class="flex items-center gap-2"><a class="px-3.5 py-2 text-xs font-semibold whitespace-nowrap">← Volver a Trabajo</a></div>';
      document.body.appendChild(baseline);
      const result = { candidate: candidate?.getBoundingClientRect().height || 0, baseline: baseline.getBoundingClientRect().height };
      baseline.remove();
      return result;
    });
    expect(heights.candidate).toBeLessThanOrEqual(heights.baseline);
  });
});
