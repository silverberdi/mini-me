import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { once } from 'node:events';
import { resolve } from 'node:path';
import { expect, test, type BrowserContext, type Page } from '@playwright/test';
import { E2E_SESSION_TOKEN, setupAuthSession, TEST_PROJECT_ID } from './helpers';

let mcpServer: ChildProcessWithoutNullStreams;
let endpoint = '';

test.beforeAll(async () => {
  const repositoryRoot = resolve(process.cwd(), '..');
  mcpServer = spawn(
    process.env['PYTHON'] || 'python3',
    ['-u', '-c', [
      'import time',
      'from tests.mcp_controlled_server import controlled_server',
      'server, endpoint = controlled_server()',
      'print(endpoint, flush=True)',
      'time.sleep(3600)',
    ].join('\n')],
    { cwd: repositoryRoot, stdio: 'pipe' },
  );
  const ready = new Promise<string>((resolveEndpoint, reject) => {
    const timer = setTimeout(() => reject(new Error('Controlled MCP server did not start.')), 5000);
    mcpServer.stdout.on('data', (chunk: Buffer) => {
      const value = chunk.toString().trim().split('\n').find(line => line.startsWith('http://'));
      if (value) {
        clearTimeout(timer);
        resolveEndpoint(value);
      }
    });
    mcpServer.once('error', error => {
      clearTimeout(timer);
      reject(error);
    });
    mcpServer.once('exit', code => {
      clearTimeout(timer);
      reject(new Error(`Controlled MCP server exited before readiness (${code}).`));
    });
  });
  endpoint = await ready;
});

test.afterAll(async () => {
  if (mcpServer && mcpServer.exitCode === null) {
    mcpServer.kill('SIGTERM');
    await once(mcpServer, 'exit');
  }
});

async function registerConnection(page: Page, name: string, isGlobal: boolean): Promise<void> {
  await page.getByRole('button', { name: 'Nueva integración MCP' }).click();
  await page.locator('input[name="name"]').fill(name);
  await page.locator('input[name="endpoint"]').fill(endpoint);
  await page.locator('input[type="radio"][name="auth_type"][value="bearer"]').check({ force: true });
  await page.locator('input[name="bearerToken"]').fill('mcp-e2e-token');
  if (isGlobal) await page.locator('input[name="isGlobal"]').check({ force: true });
  await page.getByRole('button', { name: 'Registrar y comprobar' }).click();
  await expect(page.getByRole('heading', { name })).toBeVisible();
}

test('real API registers, lists and filters project and global MCP connections', async ({ context, page }: { context: BrowserContext; page: Page }) => {
  await setupAuthSession(context, E2E_SESSION_TOKEN, TEST_PROJECT_ID);
  const suffix = Date.now().toString(36);
  const localName = `e2e-local-${suffix}`;
  const globalName = `e2e-global-${suffix}`;

  await page.goto('/conexiones-mcp');
  await registerConnection(page, localName, false);
  await registerConnection(page, globalName, true);

  await expect(page.getByText('Local · e2e-project')).toHaveCount(1);
  await expect(page.getByText('Global · heredada')).toHaveCount(1);
  await expect(page.getByText('mcp-e2e-token')).toHaveCount(0);

  await page.getByLabel('Filtrar conexiones').selectOption('global');
  await expect(page.getByRole('heading', { name: globalName })).toBeVisible();
  await expect(page.getByRole('heading', { name: localName })).toHaveCount(0);
  await page.getByLabel('Filtrar conexiones').selectOption('local');
  await expect(page.getByRole('heading', { name: localName })).toBeVisible();
  await expect(page.getByRole('heading', { name: globalName })).toHaveCount(0);
});
