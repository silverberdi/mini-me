import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const root = new URL('../src/app/', import.meta.url);
const read = (path) => fs.readFileSync(new URL(path, root), 'utf8');
const component = read('features/admin-models/admin-models.component.ts');
const routes = read('app.routes.ts');
const shell = read('app.component.ts');

test('administration route reads the real catalogs and renders observed harness results', () => {
  assert.match(routes, /path: 'administracion\/modelos-proveedores', component: AdminModelsComponent/);
  assert.match(shell, /routerLink="\/administracion\/modelos-proveedores"[\s\S]*?Administración/);
  assert.match(component, /\/api\/v1\/admin\/providers\/catalog/);
  assert.match(component, /\/api\/v1\/admin\/providers\/refresh/);
  assert.match(component, /this\.harnessResults = response\.data\.results/);
  assert.match(component, /\.\.\.\(this\.harnessResults \|\| \[\]\)\.map/);
  assert.match(component, /observed\?\.status \|\| ''/);
  assert.match(component, /Actualiza el estado para obtener una observación real/);
});

test('model toggle sends the row version and changes UI state only from server success', () => {
  assert.match(component, /\/api\/v1\/admin\/providers\/models\/\$\{encodeURIComponent\(model\.id\)\}\/enabled/);
  assert.match(component, /\{ is_enabled: requestedState, version: model\.version \}/);
  assert.match(component, /if \(response\.ok && response\.data\) \{[\s\S]*?models: \(this\.catalog\?\.models \|\| \[\]\)\.map/);
  assert.match(component, /No se pudo cambiar \$\{model\.canonical_model_id\}/);
  assert.match(component, /discovery_status/);
  assert.match(component, /is_enabled/);
});

test('role assignment uses selected project profiles and the existing project API', () => {
  assert.match(component, /key: 'thinking', label: 'Thinker'/);
  assert.match(component, /key: 'execution', label: 'Implementer'/);
  assert.match(component, /key: 'independent_review', label: 'Reviewer'/);
  assert.match(component, /'\/api\/v1\/projects'/);
  assert.match(component, /\/api\/v1\/projects\/\$\{encodeURIComponent\(projectId\)\}/);
  assert.match(component, /agent_profiles: profiles/);
  assert.match(component, /fallback/);
  assert.match(component, /Asignaciones guardadas y confirmadas por el servidor/);
});

test('AdminModelsComponent omits artificial test connection controls in compliance with Contrato Rector 2.0', () => {
  assert.doesNotMatch(component, /Test Connection/);
  assert.doesNotMatch(component, /testConnection/);
  assert.doesNotMatch(component, /\/test/);
  assert.doesNotMatch(component, /diagnosticStatusLabel/);
  assert.doesNotMatch(component, /connectionDiagnostics/);
  assert.doesNotMatch(component, /testingProviders/);
});
