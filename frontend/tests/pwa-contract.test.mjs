import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = (name) => fs.readFileSync(path.join(root, name), 'utf8');

test('service worker is shell-only and has no API data groups', () => {
  const config = JSON.parse(read('ngsw-config.json'));
  assert.equal(config.assetGroups.length, 1);
  assert.equal(config.assetGroups[0].name, 'public-shell');
  assert.equal(config.dataGroups, undefined);
  assert.ok(config.navigationUrls.includes('!/api/**'));
});

test('Angular entrypoint registers the public-shell worker', () => {
  const main = read('src/main.ts');
  assert.match(main, /provideServiceWorker\('ngsw-worker\.js'/);
  assert.match(main, /registerWhenStable:30000/);
});

test('offline API policy blocks non-GET requests before fetch', () => {
  const api = read('src/app/core/api.service.ts');
  assert.match(api, /method !== "GET"/);
  assert.match(api, /Acción no disponible sin conexión/);
  assert.match(api, /credentials: "same-origin"/);
});

test('refresh lifecycle marks retained observations stale and refreshes on reconnect', () => {
  const refresh = read('src/app/core/refresh.service.ts');
  assert.match(refresh, /readonly stale = signal<boolean>\(false\)/);
  assert.match(refresh, /addEventListener\('online'/);
  assert.match(refresh, /void this\.read\(\)/);
  assert.match(refresh, /removeEventListener\('offline'/);
});
