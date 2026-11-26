import { defineConfig, devices } from '@playwright/test';
import { resolve } from 'node:path';

const PORT = process.env['PORT'] || '8788';
const BASE_URL = `http://127.0.0.1:${PORT}`;
const SOURCE_ROOT = resolve(process.cwd(), '../src');
const E2E_DATABASE_URL = process.env['MINIME_TEST_DATABASE_URL'];
if (!E2E_DATABASE_URL) {
  throw new Error('Playwright requires MINIME_TEST_DATABASE_URL for its disposable test database.');
}
const databaseName = new URL(E2E_DATABASE_URL).pathname.replace(/^\//, '');
if (!/(^|_)test$/i.test(databaseName)) {
  throw new Error(`Playwright refuses database '${databaseName}'; the configured database name must end in '_test'.`);
}

export default defineConfig({
  testDir: './e2e',
  timeout: 30000,
  expect: {
    timeout: 5000,
  },
  fullyParallel: false,
  forbidOnly: !!process.env['CI'],
  retries: process.env['CI'] ? 1 : 0,
  workers: 1,
  reporter: process.env['CI'] ? [['list'], ['github']] : 'list',
  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'off',
    headless: true,
    launchOptions: {
      args: ['--no-sandbox', '--disable-gpu'],
    },
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: process.env['E2E_SERVER_CMD'] || `python3 -m uvicorn minime.api.app:app --host 127.0.0.1 --port ${PORT}`,
    url: `${BASE_URL}/health/live`,
    cwd: '..',
    env: {
      MINIME_DATABASE_URL: E2E_DATABASE_URL,
      MINIME_TEST_DATABASE_URL: E2E_DATABASE_URL,
      MINIME_MCP_MASTER_KEY: 'a_bUMQywh0KTjnAHHtsAuqL757W_pfDcvEH83lChrGk=',
      MINIME_AUTH_ENABLED: process.env['MINIME_AUTH_ENABLED'] || 'false',
      PYTHONPATH: [SOURCE_ROOT, process.env['PYTHONPATH']].filter(Boolean).join(':'),
    },
    reuseExistingServer: false,
    timeout: 30000,
  },
});
