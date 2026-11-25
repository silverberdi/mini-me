import { test, expect } from '@playwright/test';
import { TEST_PROJECT_ID, setupAuthSession, waitForAppMounted } from './helpers';

test('structured Human Gate keeps audit collapsed and submits the authoritative option', async ({ context, page }) => {
  await setupAuthSession(context, undefined, TEST_PROJECT_ID);
  await page.goto('/trabajo-actual?run=e2e-human-gate-run');
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
  await expect(page.getByText(/Respuesta aceptada\./i)).toBeVisible();

  await page.reload();
  await waitForAppMounted(page);
  await expect(page.locator('app-root')).toBeVisible();
});
