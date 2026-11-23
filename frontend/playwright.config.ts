import { defineConfig, devices } from '@playwright/test';
import { resolve } from 'node:path';

const PORT = process.env['PORT'] || '8788';
const BASE_URL = `http://127.0.0.1:${PORT}`;
const SOURCE_ROOT = resolve(process.cwd(), '../src');

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
      MINIME_DATABASE_URL:
        process.env['MINIME_DATABASE_URL'] ||
        process.env['MINIME_TEST_DATABASE_URL'] ||
        'postgresql+psycopg://minime_app:360bedbc1f64cd48bbb04f7934ee13bb3ed76ee368aa4a774a23be987587639c@192.168.0.194:5432/minime_test',
      PYTHONPATH: [SOURCE_ROOT, process.env['PYTHONPATH']].filter(Boolean).join(':'),
    },
    reuseExistingServer: !process.env['CI'],
    timeout: 30000,
  },
});
