import { expect, test } from '@playwright/test';
import { setupAuthSession, waitForAppMounted } from './helpers';

test.use({ serviceWorkers: 'block' });

const quotaResponse = (quota: Record<string, unknown>) => ({
  providers: [
    {
      provider: 'deepseek',
      model_id: 'deepseek-v4-pro',
      state: 'Normal',
      source: 'e2e',
      observed_at: '2026-11-22T12:00:00Z',
      ...quota,
    },
    {
      provider: 'codex',
      model_id: 'codex-e2e',
      state: 'Normal',
      source: 'e2e',
      observed_at: '2026-11-22T12:00:00Z',
      remaining_percent: 42,
    },
  ],
});

async function stubQuotaObservation(page: import('@playwright/test').Page, quota: Record<string, unknown>) {
  await page.route('**/api/**', async route => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === '/api/v1/events') return route.abort();
    let body: unknown = [];
    if (pathname === '/api/v1/auth/me') body = { authenticated: true, user: { email: 'e2e@example.com', name: 'E2E' } };
    else if (pathname === '/api/v1/providers/quotas') body = quotaResponse(quota);
    else if (pathname === '/api/v1/dashboard/overview') body = { cost: { status: 'no_data', providers: [], series: [] } };
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
}

test.describe('Dashboard capacity balance', () => {
  test('renders a verified balance inside the shared gauge at desktop and mobile sizes', async ({ context, page }) => {
    await setupAuthSession(context);
    await stubQuotaObservation(page, { balance: 20.18, currency: 'USD', remaining_percent: null });
    await page.goto('/dashboard');
    await waitForAppMounted(page);

    const card = page.locator('app-analog-gauge', { hasText: 'DeepSeek' });
    const value = card.getByTestId('gauge-text-value');
    const gauge = card.locator('svg');
    const codexCard = page.locator('app-analog-gauge', { hasText: 'Codex' });
    const codexGauge = codexCard.locator('svg');

    for (const viewport of [{ width: 1280, height: 800 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(viewport);
      await expect(value).toHaveText('$20.18 USD');
      await expect(value).not.toContainText('%');
      await expect(value).not.toContainText('—');
      await expect(gauge).toBeVisible();
      await expect(codexGauge).toBeVisible();
      await expect(codexCard.getByTestId('gauge-text-value')).toHaveText('42%');
      const [deepseekWidth, codexWidth] = await Promise.all([
        gauge.evaluate(element => element.getBoundingClientRect().width),
        codexGauge.evaluate(element => element.getBoundingClientRect().width),
      ]);
      expect(deepseekWidth).toBe(codexWidth);
      const progressOffset = await gauge.locator('path').nth(1).evaluate(element =>
        Number.parseFloat((element as SVGPathElement).style.strokeDashoffset),
      );
      expect(progressOffset).toBeCloseTo(179.07, 2);
      await expect(page.locator('body')).toHaveJSProperty('scrollWidth', viewport.width);
    }
  });

  test('keeps an unverified DeepSeek capacity unknown', async ({ context, page }) => {
    await setupAuthSession(context);
    await stubQuotaObservation(page, { balance: null, currency: null, remaining_percent: null });
    await page.goto('/dashboard');
    await waitForAppMounted(page);

    const card = page.locator('app-analog-gauge', { hasText: 'DeepSeek' });
    await expect(card.getByText('—')).toBeVisible();
    await expect(card.locator('svg')).toBeVisible();
    await expect(card).not.toContainText('$0.00');
    await expect(card).not.toContainText('%');
  });
});
