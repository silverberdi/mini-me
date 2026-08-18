# Deployment and Human Validation

## Container-first contract
Current project deployments use containers and should continue to do so. A project owns its build/up/health/down mechanics; mini me invokes and records them.

## Human validation scope
Human validation is for **UI behavior**. Services/APIs are validated automatically except as dependencies required to make the integrated UI candidate functional.

## Required OpenSpec metadata for UI changes
Any change requiring human validation must define:
- that human validation is required;
- `surface: ui`;
- scenario IDs/titles;
- preconditions;
- user-level steps;
- expected visible outcomes.

A UI change that requires human validation is not READY without those scenarios.

## Preview
Project setup/config must define a stable preview UI endpoint/port and safe container strategy. Internally multiple services may run; the human-facing contract is the UI URL.

Preview preflight must ensure production data stores are not used accidentally.

## Candidate identity
Human validation is tied to:
- repository/project binding;
- base SHA;
- candidate head SHA;
- immutable container image digest when applicable.

If candidate head changes, or base drift materially alters the effective candidate, validation becomes stale and must be repeated as policy requires.

## Recommended lifecycle
1. Build candidate.
2. Checks/review/audit pass to the required gate.
3. Commit + push candidate.
4. Create/update draft PR.
5. Build immutable image from exact candidate.
6. Deploy preview.
7. Health/smoke verification.
8. Present UI URL and guided scenarios.
9. Human marks each required scenario PASS/FAIL/SKIPPED-with-reason and decides.
10. On approval, PR becomes ready for human merge.
11. After merge, promote the validated immutable artifact when compatible; otherwise rebuild only under explicit safe policy and re-establish identity.
12. Production health/smoke checks.
13. Close only after successful operational finalization.

## Production
Production deployment may be automatic after human merge only when the project explicitly authorizes it. Failure blocks DONE and surfaces actionable evidence.

Rollback is an explicit human action in MVP, executed by mini me using the project's rollback contract and followed by verification.
