import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const sourceRoot = new URL('../src/app/', import.meta.url);
const dashboardSrc = fs.readFileSync(new URL('features/dashboard/dashboard.component.ts', sourceRoot), 'utf8');
const gaugeSrc = fs.readFileSync(new URL('shared/analog-gauge.component.ts', sourceRoot), 'utf8');

test('DeepSeek prioritizes a finite observed balance only when percentage is unavailable', () => {
  assert.match(dashboardSrc, /deepseekTextValue/);
  assert.match(dashboardSrc, /Number\.isFinite\(q\.balance\)/);
  assert.match(dashboardSrc, /q\.currency\?\.trim\(\)/);
  assert.match(dashboardSrc, /`\$\$\{q\.balance\.toFixed\(2\)\} \$\{q\.currency\.trim\(\)\}`/);
  assert.match(dashboardSrc, /remaining_percent.*Number\.isFinite/);
  assert.match(dashboardSrc, /\[textValue\]="deepseekTextValue"/);
});

test('balance presentation remains inside the shared gauge while unverified progress stays neutral', () => {
  assert.doesNotMatch(gaugeSrc, /\*ngIf="textValue; else scaledGauge"/);
  assert.match(gaugeSrc, /<!-- 270-degree Arc SVG Gauge -->/);
  assert.match(gaugeSrc, /data-testid="gauge-text-value"/);
  assert.match(gaugeSrc, /textValue \?\? \(value === null \? '—' : value \+ unit\)/);
  assert.match(gaugeSrc, /@Input\(\) textValue: string \| null = null/);
  assert.match(gaugeSrc, /stroke-dashoffset/);
  assert.match(gaugeSrc, /value === null \? '—' : value/);
});

test('unknown DeepSeek observations do not invent a balance, percentage, or currency', () => {
  const deepseekSection = dashboardSrc.slice(dashboardSrc.indexOf('get deepseekValue'), dashboardSrc.indexOf('get openrouterValue'));
  assert.match(deepseekSection, /if \(this\.deepseekValue !== null \|\| !q \|\| q\.balance === null/);
  assert.doesNotMatch(deepseekSection, /q\.currency \|\| 'USD'/);
});
