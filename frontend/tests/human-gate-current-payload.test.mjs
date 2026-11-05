import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const component = fs.readFileSync(
  path.join(root, 'src/app/features/trabajo-actual/trabajo-actual.component.ts'),
  'utf8',
);

test('Trabajo actual reads the current Run payload without stale fallbacks', () => {
  assert.match(component, /run\.stop_details\?\.\['human_payload'\]/);
  assert.doesNotMatch(component, /human_request/);
  assert.doesNotMatch(component, /metadata\?\.\['human_payload'\]/);
});

test('current gate question and options are rendered from the same payload', () => {
  assert.match(component, /humanGateQuestion\(\)/);
  assert.match(component, /humanGateOptions\(\)/);
  assert.match(component, /Opciones para responder a este gate/);
});

test('Trabajo actual fallback never selects an inactive historical run', () => {
  const targetRun = component.match(/readonly targetRun = computed\(\(\) => \{([\s\S]*?)\n  \}\);/);
  assert.ok(targetRun, 'targetRun computed selector should exist');
  assert.match(targetRun[1], /const queryRunId = this\.route\.snapshot\.queryParamMap\.get\('run'\)/);
  assert.match(targetRun[1], /if \(found\) return found/);

  const fallback = targetRun[1].match(/return (runs\.find\(r => r\.is_active\) \|\| null);/);
  assert.ok(fallback, 'fallback should select an active run or none');
  const selectFallback = new Function('runs', `return ${fallback[1]};`);
  assert.equal(selectFallback([{ is_active: false, status: 'HUMAN_REQUIRED' }]), null);
  assert.equal(selectFallback([{ is_active: true, status: 'HUMAN_REQUIRED' }]).is_active, true);
});

test('operator response submits through the existing authorized request endpoint', () => {
  assert.match(component, /\/api\/v1\/projects\/\$\{encodeURIComponent\(run\.project_id\)\}\/requests\/run/);
  assert.match(component, /operator_clarification: answer/);
  assert.match(component, /await this\.refresh\.read\(\)/);
});
