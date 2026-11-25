import { test, expect } from '@playwright/test';

test.describe('MCP connections', () => {
  test('operator can open the dedicated MCP route and sees the catalog heading', async ({ page }) => {
    await page.goto('/conexiones-mcp');
    await expect(page).toHaveURL(/\/conexiones-mcp$/);
    await expect(page.getByRole('heading', { name: 'Conexiones MCP' })).toBeVisible();
  });

  test('desktop and tablet retain the dedicated navigation entry', async ({ page }) => {
    for (const width of [1280, 768]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto('/conexiones-mcp');
      await expect(page.getByText('Conexiones MCP', { exact: true })).toBeVisible();
    }
  });
});
