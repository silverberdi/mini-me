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
    await expect(page.getByRole('link', { name: 'Conexiones MCP' })).toBeVisible();
  }
});

test('operator sees and filters global MCP connections and can register one', async ({ page }) => {
  const local = { id: 'local-1', name: 'Local GitHub', endpoint: 'http://local.test/mcp', transport: 'http', auth_type: 'bearer', status: 'ACTIVE', is_global: false, capabilities: [] };
  const global = { id: 'global-1', name: 'Global Stitch', endpoint: 'http://global.test/mcp', transport: 'http', auth_type: 'bearer', status: 'ACTIVE', is_global: true, capabilities: [] };
  let connections = [local, global];
  let registeredPayload: Record<string, unknown> | undefined;
  await page.unroute('**/api/**');
  await page.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith('/mcp-connections') && request.method() === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ connections }) });
    } else if (path.endsWith('/mcp-connections') && request.method() === 'POST') {
      registeredPayload = request.postDataJSON() as Record<string, unknown>;
      connections = [...connections, { ...global, id: 'global-2', name: String(registeredPayload['name']), endpoint: String(registeredPayload['endpoint']) }];
      await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(connections.at(-1)) });
    } else if (path === '/api/v1/auth/me') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ authenticated: true, user: { email: 'e2e@example.com' } }) });
    } else if (path === '/api/v1/projects') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([{ project_id: 'e2e-project', name: 'E2E Project', status: 'ACTIVE' }]) });
    } else {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
    }
  });

  await page.goto('/conexiones-mcp');
  await expect(page.getByText('Global · heredada')).toBeVisible();
  await expect(page.getByText('Local · e2e-project')).toBeVisible();
  await page.getByLabel('Filtrar conexiones').selectOption('global');
  await expect(page.getByRole('heading', { name: 'Global Stitch' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Local GitHub' })).toHaveCount(0);

  await page.getByRole('button', { name: 'Nueva integración MCP' }).click();
  await page.locator('input[name="name"]').fill('Shared design tools');
  await page.locator('input[name="endpoint"]').fill('http://shared.test/mcp');
  await page.locator('label:has(input[value="bearer"])').click();
  await page.locator('input[name="bearerToken"]').fill('test-token');
  await page.getByLabel('Disponible globalmente').check({ force: true });
  await page.getByRole('button', { name: 'Registrar y comprobar' }).click();

  await expect.poll(() => registeredPayload?.['is_global']).toBe(true);
  await expect(page.getByRole('heading', { name: 'Shared design tools' })).toBeVisible();
  await expect(page.getByText('test-token')).toHaveCount(0);
});
