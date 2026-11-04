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
  assert.match(component, /run\.stop_details\?\.human_payload/);
  assert.doesNotMatch(component, /human_request/);
  assert.doesNotMatch(component, /metadata\?\.\['human_payload'\]/);
});

test('current gate question and options are rendered from the same payload', () => {
  assert.match(component, /humanGateQuestion\(\)/);
  assert.match(component, /humanGateOptions\(\)/);
  assert.match(component, /Opciones para responder a este gate/);
});

test('operator response submits through the existing authorized request endpoint', () => {
  assert.match(component, /\/api\/v1\/projects\/\$\{encodeURIComponent\(run\.project_id\)\}\/requests\/run/);
  assert.match(component, /operator_clarification: answer/);
  assert.match(component, /await this\.refresh\.read\(\)/);
});
