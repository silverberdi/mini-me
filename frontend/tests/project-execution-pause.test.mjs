import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const sourceRoot = new URL('../src/app/', import.meta.url);
const models = fs.readFileSync(new URL('core/models.ts', sourceRoot), 'utf8');
const component = fs.readFileSync(new URL('features/proyectos/proyectos.component.ts', sourceRoot), 'utf8');

test('project policy exposes optional execution pause flags', () => {
  assert.match(models, /export interface ProjectExecutionPolicy \{[\s\S]*?effective_pause\?: boolean;[\s\S]*?global_pause\?: boolean;/);
});

test('project pause badge follows effective_pause independently of administrative status', () => {
  assert.match(component, /\*ngIf="proj\.execution_policy\?\.effective_pause === true"[\s\S]*?Pausado/);
  assert.match(component, /\{\{ proj\.status \|\| 'ACTIVE' \}\}[\s\S]*?proj\.execution_policy\?\.effective_pause === true/);
});

test('global pause indicator reads current refreshed projects and disappears when the flag clears', () => {
  assert.match(component, /\*ngIf="isGlobalPauseActive\(\)"[\s\S]*?Pausado globalmente/);
  assert.match(component, /isGlobalPauseActive\(\): boolean \{\s*return this\.refresh\.projects\(\)\.some\(project => project\.execution_policy\?\.global_pause === true\);\s*\}/);
});

test('existing project pause control remains based on administrative status', () => {
  assert.match(component, /\(click\)="toggleProjectPause\(\)"[\s\S]*?refresh\.activeProject\(\)\.status === 'PAUSED' \? '▶ Reanudar' : '⏸ Pausar'/);
});
