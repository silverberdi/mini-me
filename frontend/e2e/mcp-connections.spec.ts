import { test, expect } from '@playwright/test';
import { setupAuthSession } from './helpers';

test.beforeEach(async ({ context, page }) => {
  await setupAuthSession(context);
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    const body = path === '/api/v1/auth/me' ? { authenticated: true, user: { email: 'e2e@example.com', name: 'E2E' } } : path === '/api/v1/projects' ? [{ project_id: 'e2e-project', name: 'E2E Project', status: 'ACTIVE' }] : path.endsWith('/mcp-connections') ? { connections: [] } : [];
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
});

test('operator opens the dedicated MCP connections route', async ({ page }) => {
  await page.goto('/conexiones-mcp');
  await expect(page).toHaveURL(/\/conexiones-mcp$/);
  await expect(page.getByRole('heading', { name: 'Conexiones MCP' })).toBeVisible();
});

test('desktop and tablet expose the MCP navigation entry', async ({ page }) => {
  for (const width of [1280, 768]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/conexiones-mcp');
    await expect(page.getByText('Conexiones MCP', { exact: true })).toBeVisible();
  }
});
