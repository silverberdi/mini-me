import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import { HUMAN_GATE_PROJECT_ID, setupAuthSession, waitForAppMounted, E2E_SESSION_TOKEN } from './helpers';

const fixture = resolve(process.cwd(), '../tests/human_gate_ui_fixture.py');

function prepareFixture(action: 'create' | 'cleanup'): void {
  execFileSync(process.env['PYTHON'] || 'python3', [fixture, action], {
    cwd: resolve(process.cwd(), '..'),
    env: { ...process.env, MINIME_TEST_DATABASE_URL: process.env['MINIME_TEST_DATABASE_URL'] },
    stdio: 'inherit',
  });
}

test('structured Human Gate keeps audit collapsed and submits the authoritative option', async ({ context, page }) => {
  prepareFixture('create');
  try {
    await setupAuthSession(context, E2E_SESSION_TOKEN, HUMAN_GATE_PROJECT_ID);
    const runsLoaded = page.waitForResponse(response =>
      response.url().includes('/api/v1/orchestration/runs?project_id=e2e-human-gate-project') &&
      response.status() === 200);
    await page.goto(`/trabajo-actual?run=${encodeURIComponent('e2e-human-gate-run')}`);
    await runsLoaded;
    await page.reload();
    await waitForAppMounted(page);

  await expect(page.getByTestId('human-gate-summary')).toBeVisible({ timeout: 15000 });
  await expect(page.getByText('Resumen para decidir:')).toBeVisible();
  await expect(page.getByText('Pendientes y advertencias')).toBeVisible();

  const audit = page.getByTestId('human-gate-audit');
  await expect(audit).toBeVisible();
  await expect(audit.locator('summary')).toHaveText('Detalles técnicos y auditoría');
  await expect(audit).not.toHaveAttribute('open', '');
  await audit.locator('summary').click();
  await expect(audit).toHaveAttribute('open', '');

  const option = page.getByRole('button', { name: /Continuar con la validación|Cancelar el Run/i }).first();
  await expect(option).toBeVisible();
  await option.click();
  const answer = await page.locator('textarea#clarificationInput').inputValue();
  expect(answer).toBeTruthy();

  const responsePromise = page.waitForResponse(response =>
    response.url().includes('/requests/run') && response.request().method() === 'POST');
  await page.getByRole('button', { name: /Enviar respuesta y continuar/i }).click();
  const response = await responsePromise;
  expect(response.status()).toBeLessThan(300);
  const responseBody = await response.json();
  expect(responseBody.status).toBe('ACCEPTED');
  await expect(page.getByText(/Respuesta aceptada\./i)).toBeVisible();

  await expect.poll(async () => {
    const authoritativeRun = await page.request.get(
      `/api/v1/orchestration/runs?project_id=${encodeURIComponent(HUMAN_GATE_PROJECT_ID)}&is_active=true`,
      { headers: { Authorization: `Bearer ${E2E_SESSION_TOKEN}` } },
    );
    expect(authoritativeRun.ok()).toBeTruthy();
    const runs = await authoritativeRun.json();
    const run = runs.find((candidate: { run_id?: string }) => candidate.run_id === 'e2e-human-gate-run');
    return run;
  }, { timeout: 15000 }).toEqual(expect.objectContaining({
    run_id: 'e2e-human-gate-run',
    project_id: HUMAN_GATE_PROJECT_ID,
    current_stage: 'PROPOSING',
    status: 'HUMAN_REQUIRED',
    human_gate: 'HUMAN_REQUIRED',
    stop_outcome: 'NEEDS_HUMAN',
  }));

  await page.reload();
  await waitForAppMounted(page);
  await expect(page.locator('app-root')).toBeVisible();
  } finally {
    prepareFixture('cleanup');
  }
});
