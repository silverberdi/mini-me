import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const sourceRoot = new URL('../src/app/', import.meta.url);
const refresh = fs.readFileSync(new URL('core/refresh.service.ts', sourceRoot), 'utf8');
const component = fs.readFileSync(new URL('features/trabajo-actual/trabajo-actual.component.ts', sourceRoot), 'utf8');

test('new SSE events trigger an authoritative refresh while quota handling and polling remain', () => {
  for (const eventName of [
    'run.gate_acknowledged',
    'project.pause_changed',
    'request.created',
    'request.deactivated',
    'request.reactivated',
  ]) {
    assert.match(refresh, new RegExp(`addEventListener\\('${eventName}', refresh\\)`));
  }
  assert.match(refresh, /const refresh = \(\) => void this\.read\(\);/);
  assert.match(refresh, /addEventListener\('quota\.update', \(event: MessageEvent\)/);
  assert.match(refresh, /setInterval\(\(\) => \{\s*void this\.read\(\);/);
});

test('gate response hides the current question and shows processing feedback only while pending', () => {
  assert.match(component, /\*ngIf="isGateResponsePending\(\)"[\s\S]*?Respuesta enviada, procesando/);
  assert.match(component, /\*ngIf="isHumanRequired\(\)"/);
  assert.match(component, /pendingGateAcknowledgement\.set\(\{ runId: run\.run_id, identity: gateIdentity \}\);[\s\S]*?this\.api\.post/);
  assert.match(component, /this\.submissionMessage\.set\('Respuesta enviada, procesando…'\);/);
});

test('failed HTTP and transport responses restore the gate, then authoritative Run state reconciles it', () => {
  assert.match(component, /\} else \{\s*this\.pendingGateAcknowledgement\.set\(null\);/);
  assert.match(component, /catch \(e: any\) \{\s*this\.pendingGateAcknowledgement\.set\(null\);/);
  assert.match(component, /effect\(\(\) => \{[\s\S]*?this\.refresh\.runs\(\)\.find[\s\S]*?this\.humanGateIdentity\(run\) !== pending\.identity[\s\S]*?pendingGateAcknowledgement\.set\(null\)/);
  assert.match(component, /async submitHumanResponse[\s\S]*?await this\.refresh\.read\(\);/);
});
