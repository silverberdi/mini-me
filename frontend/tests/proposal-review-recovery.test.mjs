import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(new URL('../src/app/features/trabajo-actual/trabajo-actual.component.ts', import.meta.url), 'utf8');

assert.match(source, /proposal-review-recovery-authorizations/);
assert.match(source, /target_run_id:\s*run\.run_id/);
assert.match(source, /proposal_review_recovery_authorization_id/);
assert.match(source, /canRecoverProposalReview\(\)/);
assert.match(source, /run\.stage === 'PROPOSAL_REVIEW'/);
assert.match(source, /'provider_error'/);
assert.match(source, /isRecoveringProposalReview\(\)/);
console.log('proposal-review recovery UI contract: PASS');
