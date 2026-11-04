import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const root = new URL('../src/app/', import.meta.url);
const backlog = fs.readFileSync(new URL('features/backlog/backlog.component.ts', root), 'utf8');
const refresh = fs.readFileSync(new URL('core/refresh.service.ts', root), 'utf8');

test('Backlog projection keeps eligible FIFO entries first and appends unique disabled issues', () => {
  assert.match(backlog, /for \(const request of this\.refresh\.requests\(\)\) \{\s*if \(request\.status !== 'ELIGIBLE'\) continue/);
  assert.match(backlog, /this\.refresh\.allRequests\(\)[\s\S]*?filter\(request => request\.status === 'DISABLED'\)/);
  assert.match(backlog, /eligibleByIssue\.set\(normalized\.issue_number, normalized\)/);
  assert.match(backlog, /new Set\(eligibleByIssue\.keys\(\)\)/);
  assert.match(backlog, /return \[\.\.\.eligible, \.\.\.disabled\]/);
  assert.match(backlog, /request\.issue_number \?\? request\.number \?\? null/);
  assert.match(refresh, /payload\.all_requests/);
  assert.doesNotMatch(refresh, /this\.requests\.set\(\[\.\.\.eligibleRequests, \.\.\.allRequests\]\)/);
});

test('Backlog shows logical state and only renders a reason supplied by the payload', () => {
  assert.match(backlog, /req\.status === 'DISABLED' \? 'Desactivado' : 'Activo'/);
  assert.match(backlog, /\*ngIf="req\.reason"[^\n]*Motivo: \{\{ req\.reason \}\}/);
  assert.match(backlog, /req\.status === 'ELIGIBLE'[\s\S]*?Desactivar/);
  assert.match(backlog, /req\.status === 'DISABLED'[\s\S]*?Reactiva(?:r)/);
  assert.doesNotMatch(backlog, /PAUSED/);
});

test('actions use existing routes and refresh only after endpoint success', () => {
  const deactivate = backlog.slice(backlog.indexOf('async deactivateRequest'), backlog.indexOf('async reactivateRequest'));
  const reactivate = backlog.slice(backlog.indexOf('async reactivateRequest'));
  assert.match(backlog, /requests\/\$\{issueNumber\}\/deactivate/);
  assert.match(backlog, /requests\/\$\{issueNumber\}\/reactivate/);
  assert.match(deactivate, /if \(res\.ok\) \{[\s\S]*?actionSuccess\.set\(true\)[\s\S]*?desactivada\.[\s\S]*?await this\.refresh\.read\(\);[\s\S]*?\} else \{\s*this\.actionSuccess\.set\(false\)/);
  assert.match(reactivate, /if \(res\.ok\) \{[\s\S]*?actionSuccess\.set\(true\)[\s\S]*?reactivada en la cola\.[\s\S]*?await this\.refresh\.read\(\);[\s\S]*?\} else \{\s*this\.actionSuccess\.set\(false\)/);
  assert.match(deactivate, /Error al desactivar:/);
  assert.match(reactivate, /Error al reactivar:/);
});
