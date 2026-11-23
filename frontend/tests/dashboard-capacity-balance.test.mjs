import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const sourceRoot = new URL('../src/app/', import.meta.url);
const dashboardSrc = fs.readFileSync(new URL('features/dashboard/dashboard.component.ts', sourceRoot), 'utf8');
const gaugeSrc = fs.readFileSync(new URL('shared/analog-gauge.component.ts', sourceRoot), 'utf8');

test('all four provider cards use the same capacity projection', () => {
  for (const provider of ['codex', 'antigravity', 'deepseek', 'openrouter']) {
    assert.match(dashboardSrc, new RegExp(`\\[value\\]="capacityGaugeValue\\('${provider}'\\)"`));
    assert.match(dashboardSrc, new RegExp(`\\[textValue\\]="capacityTextValue\\('${provider}'\\)"`));
  }
  assert.doesNotMatch(dashboardSrc, /get (codex|antigravity|deepseek|openrouter)Value/);
});

test('reported percent wins; USD fallback projects one clamped percentage for center and arc', () => {
  assert.match(dashboardSrc, /if \(reportedPercent !== null\) return reportedPercent/);
  assert.match(dashboardSrc, /balance\?\.currency === 'USD'/);
  assert.match(dashboardSrc, /balance\.amount \/ 20/);
  assert.match(dashboardSrc, /Math\.round\(\(balance\.amount \/ 20\) \* 100\)/);
  assert.match(dashboardSrc, /balance\.amount\.toFixed\(2\)/);
  assert.match(dashboardSrc, /return balance\?\.currency === 'USD' \? `\$\{this\.capacityGaugeValue\(provider\)\}%` : null/);
  assert.match(dashboardSrc, /capacitySecondaryDetail\(provider: string\)/);
  assert.match(gaugeSrc, /data-testid="capacity-secondary-detail"/);
});

test('the shared gauge always renders the same arc and centered primary value', () => {
  assert.doesNotMatch(gaugeSrc, /\*ngIf="textValue; else scaledGauge"/);
  assert.match(gaugeSrc, /<!-- 270-degree Arc SVG Gauge -->/);
  assert.match(gaugeSrc, /data-testid="gauge-text-value"/);
  assert.match(gaugeSrc, /data-testid="gauge-progress"/);
  assert.match(gaugeSrc, /textValue \?\? \(value === null \? '—' : value \+ unit\)/);
  assert.match(gaugeSrc, /@Input\(\) textValue: string \| null = null/);
  assert.match(gaugeSrc, /stroke-dashoffset/);
  assert.match(gaugeSrc, /value === null \? '—' : value/);
});
