import { test, expect } from '@playwright/test';

test.describe('MCP connections', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname;
      const body = path === '/api/v1/auth/me'
        ? { authenticated: true, user: { email: 'e2e@example.com', name: 'E2E' } }
        : path === '/api/v1/projects'
          ? [{ project_id: 'e2e-project', name: 'E2E Project', status: 'ACTIVE' }]
          : path.endsWith('/mcp-connections') ? { connections: [] } : [];
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    });
  });
  test('operator can open the dedicated MCP route and sees the catalog heading', async ({ page }) => {
    await page.goto('/conexiones-mcp');
    await expect(page).toHaveURL(/\/conexiones-mcp$/);
    await expect(page.getByRole('heading', { name: 'Conexiones MCP' })).toBeVisible();
  });

  for (const [label, width] of [['desktop', 1280], ['tablet', 768]] as const) {
    test(`${label} opens the authenticated MCP deep link`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(`/conexiones-mcp?viewport=${width}`);
      await expect(page).toHaveURL(new RegExp(`/conexiones-mcp\\?viewport=${width}$`));
      await expect(page.getByRole('heading', { name: 'Conexiones MCP' })).toBeVisible();
    });
  }
});
