import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const component = fs.readFileSync(
  path.join(root, 'src/app/features/trabajo-actual/trabajo-actual.component.ts'),
  'utf8',
);

const expected = {
  ADMITTED: 'admitted.png',
  EXPLORING: 'exploring.png',
  PROPOSING: 'proposing.png',
  PROPOSAL_REVIEW: 'proposal-review.png',
  IMPLEMENTING: 'implementing.png',
  RUNNING_TESTS: 'running-tests.png',
  VERIFYING: 'verifying.png',
  CODE_REVIEW: 'code-review.png',
  PREPARING_PR: 'preparing-pr.png',
  COMPLETED: 'completed.png',
};

test('normative stage mapping contains every exact Issue assignment', () => {
  for (const [stage, filename] of Object.entries(expected)) {
    assert.match(component, new RegExp(`${stage}: '/illustrations/${filename.replace('.', '\\.')}'`));
    assert.ok(fs.existsSync(path.join(root, 'public/illustrations', filename)));
  }
});

test('all approved illustration files are PNGs in the public asset surface', () => {
  for (const filename of Object.values(expected)) {
    const bytes = fs.readFileSync(path.join(root, 'public/illustrations', filename));
    assert.deepEqual([...bytes.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  }
});

test('unknown or absent stage has no guessed fallback image', () => {
  assert.match(component, /STAGE_ILLUSTRATION_PATHS\[stage\] \?\? null/);
  assert.match(component, /const stage = this\.targetRun\(\)\?\.stage/);
  assert.match(component, /\*ngIf="stageIllustrationPath\(\) as illustrationPath"/);
});

test('current-work card keeps navigation and puts it after supervision text', () => {
  const description = component.indexOf('Supervisión detallada de la ejecución');
  const link = component.indexOf('routerLink="/trabajo"');
  assert.ok(description >= 0 && link > description);
  assert.match(component, /routerLink="\/trabajo"[^>]*data-testid="back-to-work"/);
  assert.match(component, /whitespace-nowrap/);
  assert.match(component, /<img \[src\]="illustrationPath" alt=""/);
});

test('presentation change does not add API, route, or service-worker contracts', () => {
  assert.doesNotMatch(component, /fetch\(|provideServiceWorker|ngsw-config/);
  const routes = fs.readFileSync(path.join(root, 'src/app/app.routes.ts'), 'utf8');
  assert.match(routes, /path: 'trabajo-actual'/);
  const serviceWorker = fs.readFileSync(path.join(root, 'ngsw-config.json'), 'utf8');
  assert.doesNotMatch(serviceWorker, /dataGroups|api\/v1/);
});
