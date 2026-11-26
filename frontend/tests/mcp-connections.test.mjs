import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(new URL('../src/app/features/mcp-connections/mcp-connections.component.ts', import.meta.url), 'utf8');
const routes = fs.readFileSync(new URL('../src/app/app.routes.ts', import.meta.url), 'utf8');
const shell = fs.readFileSync(new URL('../src/app/app.component.ts', import.meta.url), 'utf8');

test('MCP has dedicated authenticated route and sidebar entry', () => {
  assert.match(routes, /path: 'conexiones-mcp'/);
  assert.match(shell, /routerLink="\/conexiones-mcp"/);
});

test('MCP UI renders sanitized status and observed capabilities', () => {
  assert.match(source, /Capacidades observadas/);
  assert.match(source, /connection\.status/);
  assert.doesNotMatch(source, /localStorage|sessionStorage|serviceWorker/);
  assert.match(source, /mcp-connections/);
});

test('MCP UI exposes scope registration, badges and catalog filtering', () => {
  assert.match(source, /name="isGlobal"/);
  assert.match(source, /connection\.is_global \? 'Global · heredada'/);
  assert.match(source, /id="mcp-scope-filter"/);
  assert.match(source, /filteredConnections\(\)/);
  assert.match(source, /is_global: this\.draft\.is_global/);
});
