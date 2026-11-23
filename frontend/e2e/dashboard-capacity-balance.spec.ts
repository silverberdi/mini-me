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
  test('renders a verified DeepSeek balance directly and stays within a mobile viewport', async ({ context, page }) => {
    await setupAuthSession(context);
    await stubQuotaObservation(page, { balance: 20.18, currency: 'USD', remaining_percent: null });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/dashboard');
    await waitForAppMounted(page);

    const card = page.locator('app-analog-gauge', { hasText: 'DeepSeek' });
    await expect(card.getByTestId('gauge-text-value')).toHaveText('$20.18 USD');
    await expect(card.getByTestId('gauge-text-value')).not.toContainText('%');
    await expect(card.getByTestId('gauge-text-value')).not.toContainText('—');
    await expect(page.locator('body')).toHaveJSProperty('scrollWidth', 390);
  });

  test('keeps an unverified DeepSeek capacity unknown', async ({ context, page }) => {
    await setupAuthSession(context);
    await stubQuotaObservation(page, { balance: null, currency: null, remaining_percent: null });
    await page.goto('/dashboard');
    await waitForAppMounted(page);

    const card = page.locator('app-analog-gauge', { hasText: 'DeepSeek' });
    await expect(card.getByText('—')).toBeVisible();
    await expect(card).not.toContainText('$0.00');
    await expect(card).not.toContainText('%');
  });
});
