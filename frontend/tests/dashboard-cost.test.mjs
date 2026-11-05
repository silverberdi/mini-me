import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

const dashboard = await readFile(new URL('../src/app/features/dashboard/dashboard.component.ts', import.meta.url), 'utf8');
const refresh = await readFile(new URL('../src/app/core/refresh.service.ts', import.meta.url), 'utf8');

test('dashboard renders ledger costs by provider/model and has an explicit no-data state', () => {
  assert.match(refresh, /\/api\/v1\/dashboard\/overview/);
  assert.match(refresh, /readonly cost = signal<DashboardCost>/);
  assert.match(dashboard, /provider\.label/);
  assert.match(dashboard, /model\.model/);
  assert.match(dashboard, /Sin datos de costo liquidado/);
  assert.doesNotMatch(dashboard, /\(r as any\)\.tokens/);
  assert.doesNotMatch(dashboard, /displayVal = 'CLI'/);
});

test('the dashboard cost chart maps API series to the SVG view model', async () => {
  const source = await readFile(
    new URL('../src/app/features/dashboard/dashboard-cost-chart.ts', import.meta.url),
    'utf8',
  );
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const chart = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
  const points = chart.toDashboardCostChartPoints([
    { day: '2026-08-01', provider: 'deepseek_direct', model: 'deepseek/deepseek-flash', amount_usd: '0.123456' },
    { day: '2026-08-01', provider: 'openrouter', model: 'openrouter/deepseek/deepseek-r1-0528', amount_usd: '1.200000' },
    { day: '2026-08-01', provider: 'openrouter', model: 'Modelo no identificado', amount_usd: '0.020000' },
  ]);

  assert.deepEqual(points.map(({ label, displayVal }) => [label, displayVal]), [
    ['deepseek_direct · deepseek/deepseek-flash', '$0.123456'],
    ['openrouter · openrouter/deepseek/deepseek-r1-0528', '$1.200000'],
    ['openrouter · Modelo no identificado', '$0.020000'],
  ]);
  assert.equal(points.length, 3);
});
