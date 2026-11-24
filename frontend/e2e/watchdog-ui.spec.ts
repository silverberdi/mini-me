import { expect, test } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import { E2E_SESSION_TOKEN, setupAuthSession, waitForAppMounted } from './helpers';

const fixtureSuffix = `${Date.now()}-${process.pid}`;
const fixtureScript = resolve(process.cwd(), '../tests/watchdog_ui_fixture.py');

function runFixture(action: 'seed' | 'cleanup'): void {
  execFileSync(process.env['PYTHON'] || 'python3', [fixtureScript, action, fixtureSuffix], {
    cwd: resolve(process.cwd(), '..'),
    env: process.env,
    stdio: 'pipe',
  });
}

test.describe('Watchdog operator surfaces', () => {
  test.beforeEach(async ({ context }) => {
    await setupAuthSession(context);
  });

  test('persists settings, filters and handles suggestions, and displays run diagnostics', async ({ page, request, context }) => {
    const headers = { Authorization: `Bearer ${E2E_SESSION_TOKEN}` };
    const projectOne = `watchdog-ui-${fixtureSuffix}-one`;
    const original = await request.get('/api/v1/admin/watchdog/settings', { headers });
    expect(original.ok()).toBe(true);
    const prior = await original.json();
    try {
      runFixture('seed');
      const updated = await request.patch('/api/v1/admin/watchdog/settings', {
        headers,
        data: {
          provider_id: null,
          harness_id: null,
          canonical_model_id: null,
          inactivity_threshold_minutes: 17,
          mode: 'mechanical_remediation',
        },
      });
      expect(updated.ok()).toBe(true);
      expect(await updated.json()).toMatchObject({ inactivity_threshold_minutes: 17, mode: 'mechanical_remediation' });
      const reread = await request.get('/api/v1/admin/watchdog/settings', { headers });
      expect(await reread.json()).toMatchObject({ inactivity_threshold_minutes: 17, mode: 'mechanical_remediation' });

      await page.goto('/administracion/modelos-proveedores');
      await waitForAppMounted(page);
      await expect(page.getByRole('heading', { name: 'Watchdog / SRE global', level: 2 })).toBeVisible();
      await expect(page.getByLabel('Umbral de inactividad (minutos)')).toHaveValue('17');

      await page.goto('/mejora-continua');
      await waitForAppMounted(page);
      await expect(page.getByRole('heading', { name: 'Mejora Continua' })).toBeVisible();
      await page.getByLabel('Proyecto Todos').selectOption(projectOne);
      await expect(page.getByText('Otra sugerencia del mismo proyecto')).toBeVisible();
      await expect(page.getByText('Sugerencia de otro proyecto')).toHaveCount(0);
      await page.getByLabel('Estado Todos').selectOption('discarded');
      await expect(page.getByText(/No hay sugerencias para estos filtros/)).toBeVisible();
      await page.getByLabel('Estado Todos').selectOption('pending');
      await expect(page.getByText('Una sugerencia pendiente para prueba')).toBeVisible();
      await context.grantPermissions(['clipboard-read', 'clipboard-write']);
      const firstSuggestion = page.locator('article').filter({ hasText: 'Una sugerencia pendiente para prueba' });
      await page.evaluate(() => {
        Object.defineProperty(window, '__watchdogClipboard', {
          value: navigator.clipboard,
          configurable: true,
        });
        Object.defineProperty(navigator, 'clipboard', {
          value: { writeText: async () => { throw new Error('clipboard denied'); } },
          configurable: true,
        });
      });
      await firstSuggestion.getByRole('button', { name: 'Copiar borrador' }).click();
      await expect(page.getByRole('alert')).toContainText('La sugerencia sigue pendiente');
      await expect(firstSuggestion).toContainText('Pendiente');
      await page.evaluate(() => Object.defineProperty(navigator, 'clipboard', {
        value: (window as Window & { __watchdogClipboard?: Clipboard }).__watchdogClipboard,
        configurable: true,
      }));
      await firstSuggestion.getByRole('button', { name: 'Copiar borrador' }).click();
      await expect(page.getByRole('status')).toContainText('Borrador copiado');
      await expect(firstSuggestion).toContainText('Copiada como borrador');
      const secondSuggestion = page.locator('article').filter({ hasText: 'Otra sugerencia del mismo proyecto' });
      await secondSuggestion.getByRole('button', { name: 'Descartar' }).click();
      await expect(secondSuggestion).toContainText('Descartada');

      const autonomyResponse = await request.get('/api/v1/dashboard/overview', { headers });
      expect(autonomyResponse.ok()).toBe(true);
      const autonomy = (await autonomyResponse.json()).temporal_telemetry.autonomy;
      expect(autonomy.no_data).toBe(false);
      expect(autonomy.units).toBe('%');
      await page.goto('/dashboard');
      await waitForAppMounted(page);
      await expect(page.getByRole('heading', { name: /Gráfica de Líneas de Efectividad/ })).toBeVisible();
      await expect(page.getByRole('button', { name: /Calidad \/ Autonomía/ })).toBeVisible();
      await expect(page.locator('svg[aria-label="Series temporales de telemetría"]')).toBeVisible();
      await page.route('**/api/v1/dashboard/overview', async route => {
        const response = await route.fetch();
        const payload = await response.json();
        payload.temporal_telemetry.autonomy.no_data = true;
        await route.fulfill({ response, json: payload });
      });
      await page.reload();
      await expect(page.getByText('Sin datos verificables para esta dimensión', { exact: true })).toBeVisible();

      await page.goto(`/trabajo-actual?run=watchdog-ui-${fixtureSuffix}-active`);
      await waitForAppMounted(page);
      await page.getByLabel('Proyecto:').selectOption(projectOne);
      await expect(page.getByLabel('Proyecto:')).toHaveValue(projectOne);
      await expect(page.getByRole('heading', { name: 'Diagnóstico & Supervisión' })).toBeVisible();
      await expect(page.getByText(/^Etapa:/)).toBeVisible();
      await expect(page.getByText(/Pulso de actividad:/)).toBeVisible();
      await expect(page.getByRole('main').getByRole('link', { name: 'Mejora Continua' })).toBeVisible();
      await expect(page.getByTestId('watchdog-timeline')).toContainText('e2e_cause_0');
      await page.getByRole('button', { name: 'Diagnosticar y destrabar ahora' }).click();
      await expect(page.getByRole('status')).toContainText('el coordinador evaluará la recuperación');
    } finally {
      try {
        const restored = await request.patch('/api/v1/admin/watchdog/settings', {
          headers,
          data: {
            provider_id: prior.provider_id,
            harness_id: prior.harness_id,
            canonical_model_id: prior.canonical_model_id,
            inactivity_threshold_minutes: prior.inactivity_threshold_minutes,
            mode: prior.mode,
          },
        });
        expect(restored.ok()).toBe(true);
      } finally {
        runFixture('cleanup');
      }
    }
  });
});
