import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const sourceRoot = new URL('../src/app/', import.meta.url);
const refresh = fs.readFileSync(new URL('core/refresh.service.ts', sourceRoot), 'utf8');
const component = fs.readFileSync(new URL('features/trabajo-actual/trabajo-actual.component.ts', sourceRoot), 'utf8');

test('new SSE events trigger targeted updates while quota handling functions without periodic polling', () => {
  for (const eventName of [
    'run.gate_acknowledged',
    'request.created',
    'request.deactivated',
    'request.reactivated',
  ]) {
    assert.match(refresh, new RegExp(`addEventListener\\('${eventName}', handleRunEvent\\)`));
  }
  assert.match(refresh, /addEventListener\('project\.pause_changed', handleProjectEvent\)/);
  assert.match(refresh, /addEventListener\('quota\.update', \(event: MessageEvent\)/);
  assert.match(refresh, /addEventListener\('run\.resync', handleRunEvent\)/);
  assert.match(refresh, /this\.events\.onopen = \(\) => \{\s*void this\.refreshRuns\(\)/);
  assert.match(refresh, /if \(!runsRes\.ok \|\| !Array\.isArray\(runsRes\.data\)\) \{\s*this\.stale\.set\(true\);\s*return;/);
  assert.doesNotMatch(refresh, /setInterval\(/);
});

test('gate response reports API acceptance immediately and waits for the authoritative Run transition', () => {
  assert.match(component, /\*ngIf="isGateResponsePending\(\)"[\s\S]*?Respuesta aceptada/);
  assert.match(component, /\*ngIf="isHumanRequired\(\)"/);
  assert.match(component, /pendingGateAcknowledgement\.set\(\{ runId: run\.run_id, identity: gateIdentity \}\);[\s\S]*?this\.api\.post/);
  assert.match(component, /DOC_CLOSING queda pendiente del Scheduler/);
  assert.match(component, /this\.submissionMessage\.set\(run\.stage === 'DOC_CLOSING'/);
  assert.match(component, /await this\.refresh\.refreshRuns\(\);/);
});

test('failed HTTP and transport responses restore the gate, then authoritative Run state reconciles it', () => {
  assert.match(component, /\} else \{\s*this\.pendingGateAcknowledgement\.set\(null\);/);
  assert.match(component, /catch \(e: any\) \{\s*this\.pendingGateAcknowledgement\.set\(null\);/);
  assert.match(component, /effect\(\(\) => \{[\s\S]*?this\.refresh\.runs\(\)\.find[\s\S]*?this\.humanGateIdentity\(run\) !== pending\.identity[\s\S]*?pendingGateAcknowledgement\.set\(null\)/);
  assert.match(component, /async submitHumanResponse[\s\S]*?await this\.refresh\.refreshRuns\(\);/);
});
