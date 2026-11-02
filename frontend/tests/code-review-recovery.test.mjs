import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(new URL('../src/app/features/trabajo-actual/trabajo-actual.component.ts', import.meta.url), 'utf8');

assert.match(source, /code-review-recovery-authorizations/);
assert.match(source, /target_run_id:\s*run\.run_id/);
assert.match(source, /code_review_recovery_authorization_id/);
assert.match(source, /canRecoverCodeReview\(\)/);
assert.match(source, /isRecoveringCodeReview\(\)/);
console.log('code-review recovery UI contract: PASS');
