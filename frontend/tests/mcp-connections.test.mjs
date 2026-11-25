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
