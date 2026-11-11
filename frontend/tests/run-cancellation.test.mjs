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

test('Run cancellation control is limited to an active human gate with no active job', () => {
  assert.match(component, /\*ngIf="canCancelHumanRun\(\)"/);
  const method = component.match(/canCancelHumanRun\(\): boolean \{([\s\S]*?)\n  \}/);
  assert.ok(method);
  assert.match(method[1], /run\.is_active/);
  assert.match(method[1], /this\.isHumanRequired\(\)/);
  assert.match(method[1], /!run\.active_job_id/);
});

test('Run cancellation asks for a reason and explicit confirmation before posting', () => {
  assert.match(component, /name="cancellationReason"/);
  const method = component.match(/async cancelHumanRun\(\): Promise<void> \{([\s\S]*?)\n  \}/);
  assert.ok(method);
  assert.match(method[1], /window\.confirm/);
  assert.match(method[1], /if \(!confirmed\) return/);
  assert.match(method[1], /runs\/\$\{encodeURIComponent\(run\.run_id\)\}\/cancel/);
  assert.match(method[1], /idempotency_key/);
});

test('Run cancellation displays server result and rejection without optimistic state', () => {
  assert.match(component, /data-testid="run-cancellation-result"/);
  assert.match(component, /Run cancelado y proyecto liberado/);
  assert.match(component, /No se canceló el Run/);
  assert.match(component, /await this\.refresh\.read\(\)/);
});
