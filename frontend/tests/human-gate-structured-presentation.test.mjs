import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const normalizer = fs.readFileSync(path.join(root, 'src/app/features/trabajo-actual/human-gate-presentation.ts'), 'utf8');
const component = fs.readFileSync(path.join(root, 'src/app/features/trabajo-actual/trabajo-actual.component.ts'), 'utf8');

function split(value) {
  if (typeof value !== 'string') return [];
  return value.split(';').map(item => item.trim()).filter(Boolean);
}

test('normalizer defines safe legacy parsing and does not mutate payload values', () => {
  assert.match(normalizer, /export function normalizeHumanGatePayload/);
  assert.match(normalizer, /value\.split/);
  assert.deepEqual(split('  Falta A; ; Falta B  '), ['Falta A', 'Falta B']);
  assert.deepEqual(split(''), []);
  assert.match(normalizer, /source\['pending_items'\]/);
  assert.match(normalizer, /source\['options_es'\]/);
});

test('structured card separates summary, warning items, choices and collapsed audit', () => {
  assert.match(component, /data-testid="human-gate-summary"/);
  assert.match(component, /humanGatePendingItems\(\)/);
  assert.match(component, /aria-label="Pendientes del gate"/);
  assert.match(component, /data-testid="human-gate-audit"/);
  assert.match(component, /Detalles técnicos y auditoría/);
  assert.match(component, /<details class="rounded-xl/);
  assert.match(component, /humanGateDisplayOptions\(\)/);
  assert.match(component, /selectHumanGateOption\(opt\)/);
});

test('technical diagnostics are only inside the collapsed disclosure', () => {
  const auditStart = component.indexOf('data-testid="human-gate-audit"');
  assert.ok(auditStart > 0);
  const beforeAudit = component.slice(0, auditStart);
  assert.doesNotMatch(beforeAudit, /<pre[\s\S]*humanGateDiff\(\)/);
  assert.match(component.slice(auditStart), /humanGateDiff\(\)/);
});
