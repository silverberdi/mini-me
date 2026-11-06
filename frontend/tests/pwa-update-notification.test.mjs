import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const component = fs.readFileSync(path.join(root, 'src/app/app.component.ts'), 'utf8');

test('ready service-worker versions show an accessible Spanish update notice', () => {
  assert.match(component, /if \(this\.swUpdate\.isEnabled\)[\s\S]*?versionUpdates\.subscribe\(\(event\) => \{[\s\S]*?event\.type === 'VERSION_READY'[\s\S]*?updateAvailable = true/);
  assert.match(component, /\*ngIf="updateAvailable"[\s\S]*?role="status" aria-live="polite"/);
  assert.match(component, /Hay una nueva versión de mini me disponible\./);
  assert.match(component, /\(click\)="loadAvailableUpdate\(\)"[\s\S]*?Recargar/);
});

test('the app activates and reloads only after the operator chooses to load the update', () => {
  const action = component.match(/async loadAvailableUpdate\(\): Promise<void> \{([\s\S]*?)\n  \}/)?.[1];
  assert.ok(action, 'loadAvailableUpdate action exists');
  assert.match(action, /if \(!this\.updateAvailable \|\| !this\.swUpdate\.isEnabled\)\s*\{\s*return;/);
  assert.match(action, /const activated = await this\.swUpdate\.activateUpdate\(\);\s*if \(activated\) \{\s*window\.location\.reload\(\);/);

  const init = component.match(/async ngOnInit\(\): Promise<void> \{([\s\S]*?)\n  \}/)?.[1];
  assert.ok(init, 'ngOnInit exists');
  assert.doesNotMatch(init, /location\.reload/);
});
