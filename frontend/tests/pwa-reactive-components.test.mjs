import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const sourceRoot = new URL('../src/app/', import.meta.url);
const refreshSrc = fs.readFileSync(new URL('core/refresh.service.ts', sourceRoot), 'utf8');
const proyectosSrc = fs.readFileSync(new URL('features/proyectos/proyectos.component.ts', sourceRoot), 'utf8');
const adminModelsSrc = fs.readFileSync(new URL('features/admin-models/admin-models.component.ts', sourceRoot), 'utf8');
const trabajoActualSrc = fs.readFileSync(new URL('features/trabajo-actual/trabajo-actual.component.ts', sourceRoot), 'utf8');
const appSrc = fs.readFileSync(new URL('app.component.ts', sourceRoot), 'utf8');

test('RefreshService has eliminated blind global periodic polling and interval timers', () => {
  // Must NOT contain setInterval or setupTimer or timer property
  assert.doesNotMatch(refreshSrc, /setInterval\(/);
  assert.doesNotMatch(refreshSrc, /setupTimer/);
  assert.doesNotMatch(refreshSrc, /private timer/);
  assert.doesNotMatch(refreshSrc, /readonly interval =/);

  // Must retain EventSource subscription for real-time reactivity
  assert.match(refreshSrc, /new EventSource\('\/api\/v1\/events'\)/);
  assert.match(refreshSrc, /addEventListener\('run\.transition', handleRunEvent\)/);
  assert.match(refreshSrc, /addEventListener\('project\.pause_changed', handleProjectEvent\)/);
  assert.match(refreshSrc, /addEventListener\('quota\.update',/);
});

test('RefreshService provides targeted update methods to avoid disrupting unrelated views', () => {
  // Targeted updates
  assert.match(refreshSrc, /async refreshRuns\(\): Promise<void>/);
  assert.match(refreshSrc, /async refreshProjects\(\): Promise<void>/);

  // 5-minute amortized cache for dashboard overview
  assert.match(refreshSrc, /DASHBOARD_CACHE_TTL_MS = 300_000/);
  assert.match(refreshSrc, /shouldFetchDashboard = force \|\| \(now - this\.lastDashboardFetchTime >= this\.DASHBOARD_CACHE_TTL_MS\)/);
});

test('ProyectosComponent isolates lifecycle and isolates project mutations', () => {
  // Loads on ngOnInit without periodic polling reset
  assert.match(proyectosSrc, /ngOnInit\(\): Promise<void>/);
  assert.match(proyectosSrc, /this\.refresh\.projects\(\)\.length === 0 \? this\.refresh\.refreshProjects\(\) : Promise\.resolve\(\)/);

  // Form submit and toggle actions use scoped refreshProjects() instead of resetting all collections
  assert.match(proyectosSrc, /submitCreateProject[\s\S]*?await this\.refresh\.refreshProjects\(\);/);
  assert.match(proyectosSrc, /submitEditProject[\s\S]*?await this\.refresh\.refreshProjects\(\);/);
  assert.match(proyectosSrc, /toggleProjectPause[\s\S]*?await this\.refresh\.refreshProjects\(\);/);
});

test('AdminModelsComponent loads models on demand without background polling interference', () => {
  // AdminModelsComponent does not inject RefreshService to prevent signal cascade resets
  assert.doesNotMatch(adminModelsSrc, /RefreshService/);
  assert.match(adminModelsSrc, /ngOnInit/);
  assert.match(adminModelsSrc, /\/api\/v1\/admin\/providers\/catalog/);
  assert.match(adminModelsSrc, /toggleModel/);
});

test('TrabajoActualComponent optimistically hides human gate and shows inline processing feedback', () => {
  // Optimistic hiding upon submit
  assert.match(trabajoActualSrc, /pendingGateAcknowledgement\.set\(\{ runId: run\.run_id, identity: gateIdentity \}\);/);
  assert.match(trabajoActualSrc, /isGateResponsePending\(\): boolean/);
  assert.match(trabajoActualSrc, /if \(this\.isGateResponsePending\(\)\) return false;/);

  // Inline feedback in template
  assert.match(trabajoActualSrc, /\*ngIf="isGateResponsePending\(\)"/);
  assert.match(trabajoActualSrc, /Respuesta enviada, procesando/);

  // Rollback on HTTP failure
  assert.match(trabajoActualSrc, /\} else \{\s*this\.pendingGateAcknowledgement\.set\(null\);/);
  assert.match(trabajoActualSrc, /catch \(e: any\) \{\s*this\.pendingGateAcknowledgement\.set\(null\);/);
});

test('Global header omits manual refresh button and syncing labels in favor of reactive events', () => {
  assert.doesNotMatch(appSrc, /button \(click\)="refresh\.read\(true\)"/);
  assert.doesNotMatch(appSrc, /aria-label="Refrescar"/);
  assert.doesNotMatch(appSrc, /Sincronizando…/);
  assert.match(appSrc, /refresh\.isConnected\(\)/);
});
