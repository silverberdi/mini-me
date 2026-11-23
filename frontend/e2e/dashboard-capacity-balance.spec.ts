import { expect, test } from '@playwright/test';
import { setupAuthSession, waitForAppMounted } from './helpers';

test.use({ serviceWorkers: 'block' });

type Quota = Record<string, unknown> & { provider: string };

function quotaResponse(providers: Quota[]) {
  return {
    providers: providers.map(quota => ({
      model_id: `${quota.provider}-test-model`,
      state: 'AVAILABLE',
      source: 'e2e',
      observed_at: '2026-11-22T12:00:00Z',
      ...quota,
    })),
  };
}

async function stubQuotaObservations(page: import('@playwright/test').Page, providers: Quota[]) {
  await page.route('**/api/**', async route => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === '/api/v1/events') return route.abort();
    let body: unknown = [];
    if (pathname === '/api/v1/auth/me') body = { authenticated: true, user: { email: 'e2e@example.com', name: 'E2E' } };
    else if (pathname === '/api/v1/providers/quotas') body = quotaResponse(providers);
    else if (pathname === '/api/v1/dashboard/overview') body = { cost: { status: 'no_data', providers: [], series: [] } };
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
}

function providerCard(page: import('@playwright/test').Page, label: string) {
  return page.locator('app-analog-gauge', { hasText: label });
}

async function arcOffset(card: ReturnType<typeof providerCard>): Promise<number> {
  const style = await card.getByTestId('gauge-progress').evaluate(element => (element as SVGPathElement).style.strokeDashoffset);
  return Number.parseFloat(style);
}

test.describe('Dashboard capacity balance', () => {
  test('uses one gauge projection and preserves OpenRouter provider percentage', async ({ context, page }) => {
    await setupAuthSession(context);
    await stubQuotaObservations(page, [
      { provider: 'codex', remaining_percent: 73, balance: 14, currency: 'USD' },
      { provider: 'antigravity', remaining_percent: null, balance: 15, currency: 'USD' },
      { provider: 'deepseek', remaining_percent: null, balance: 10, currency: 'USD' },
      { provider: 'openrouter', remaining_percent: 42, balance: 125, currency: 'USD' },
    ]);
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto('/dashboard');
    await waitForAppMounted(page);

    await expect(page.getByTestId('capacity-reference-note')).toContainText('$20 como referencia visual del 100%');
    await expect(page.locator('app-analog-gauge')).toHaveCount(4);
    await expect(providerCard(page, 'Codex').getByTestId('gauge-text-value')).toHaveText('73%');
    await expect(providerCard(page, 'Antigravity').getByTestId('gauge-text-value')).toHaveText('75%');
    await expect(providerCard(page, 'DeepSeek').getByTestId('gauge-text-value')).toHaveText('50%');
    await expect(providerCard(page, 'Antigravity').getByTestId('capacity-secondary-detail')).toContainText('$15.00 USD');
    await expect(providerCard(page, 'DeepSeek').getByTestId('capacity-secondary-detail')).toContainText('$10.00 USD');
    await expect(providerCard(page, 'DeepSeek').getByTestId('capacity-secondary-detail')).toContainText('referencia USD 20 = 100%');
    await expect(providerCard(page, 'OpenRouter').getByTestId('gauge-text-value')).toHaveText('42%');
    expect(await arcOffset(providerCard(page, 'DeepSeek'))).toBeCloseTo(89.535, 2);
    expect(await arcOffset(providerCard(page, 'Antigravity'))).toBeCloseTo(44.7675, 2);
    expect(await arcOffset(providerCard(page, 'OpenRouter'))).toBeCloseTo(103.8606, 2);

    await page.setViewportSize({ width: 390, height: 844 });
    const mobileDeepSeek = providerCard(page, 'DeepSeek');
    await expect(mobileDeepSeek.getByTestId('gauge-text-value')).toBeVisible();
    await expect(mobileDeepSeek.getByTestId('capacity-secondary-detail')).toBeVisible();
    await expect(mobileDeepSeek.getByTestId('capacity-secondary-detail')).toContainText('referencia USD 20 = 100%');
    await expect(page.locator('body')).toHaveJSProperty('scrollWidth', 390);
  });

  test('maps USD 0, 10 and above-reference balances to matching center percentages and arcs', async ({ context, page }) => {
    await setupAuthSession(context);
    const balances = [0, 10, 20.18];
    let currentBalance = balances[0];
    await page.route('**/api/**', async route => {
      const pathname = new URL(route.request().url()).pathname;
      if (pathname === '/api/v1/events') return route.abort();
      let body: unknown = [];
      if (pathname === '/api/v1/auth/me') body = { authenticated: true, user: { email: 'e2e@example.com', name: 'E2E' } };
      else if (pathname === '/api/v1/providers/quotas') {
        body = quotaResponse([{ provider: 'deepseek', remaining_percent: null, balance: currentBalance, currency: 'USD' }]);
      } else if (pathname === '/api/v1/dashboard/overview') body = { cost: { status: 'no_data', providers: [], series: [] } };
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    });
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto('/dashboard');
    await waitForAppMounted(page);

    for (const balance of balances) {
      currentBalance = balance;
      if (balance !== balances[0]) await page.reload();
      const card = providerCard(page, 'DeepSeek');
      const expectedPercent = Math.min(100, Math.max(0, Math.round(balance / 20 * 100)));
      await expect(card.getByTestId('gauge-text-value')).toHaveText(`${expectedPercent}%`);
      await expect(card.getByTestId('capacity-secondary-detail')).toContainText(`$${balance.toFixed(2)} USD`);
      expect(await arcOffset(card)).toBeCloseTo(179.07 * (1 - expectedPercent / 100), 2);
    }
  });

  test('does not use the USD scale for another currency and keeps missing data unknown', async ({ context, page }) => {
    await setupAuthSession(context);
    await stubQuotaObservations(page, [
      { provider: 'deepseek', remaining_percent: null, balance: 10, currency: 'EUR' },
    ]);
    await page.goto('/dashboard');
    await waitForAppMounted(page);

    const deepseek = providerCard(page, 'DeepSeek');
    await expect(deepseek.getByTestId('gauge-text-value')).toHaveText('—');
    await expect(deepseek.getByTestId('capacity-secondary-detail')).toContainText('10.00 EUR');
    expect(await arcOffset(deepseek)).toBeCloseTo(179.07, 2);

    const openrouter = providerCard(page, 'OpenRouter');
    await expect(openrouter.getByTestId('gauge-text-value')).toHaveText('—');
    expect(await arcOffset(openrouter)).toBeCloseTo(179.07, 2);
  });
});
