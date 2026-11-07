import { defineConfig, devices } from '@playwright/test';

const PORT = process.env['PORT'] || '8788';
const BASE_URL = `http://127.0.0.1:${PORT}`;

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
    command: process.env['E2E_SERVER_CMD'] || `python -m uvicorn minime.api.app:app --host 127.0.0.1 --port ${PORT}`,
    url: `${BASE_URL}/health/live`,
    cwd: '..',
    reuseExistingServer: !process.env['CI'],
    timeout: 30000,
  },
});
