## 1. Evidence model and assessment

- [x] 1.1 Inventory task, acceptance-scenario, configured-agent, workflow-installation, project-context, and candidate-hash sources used by the existing Propose/complexity path.
- [x] 1.2 Extend the structured thinking assessment to map every validated OpenSpec task and acceptance scenario to a responsible actor, available capability evidence, satisfied preconditions, and observable completion evidence.
- [x] 1.3 Validate complete task/scenario coverage and verify cited repository paths and configured workflows against the confined candidate and project profile; treat unknown or unverified external evidence as blocked.

## 2. Proposal acceptance gate

- [x] 2.1 Persist the feasibility assessment with the exact Request-context and OpenSpec artifact hashes in existing PostgreSQL Run state.
- [x] 2.2 Keep a blocked or incomplete proposal unaccepted at the existing human gate before complexity review/Apply; show every blocked task/scenario and required evidence without consuming Apply attempts.
- [x] 2.3 Re-evaluate only after authoritative Request or capability evidence changes; require native OpenSpec Update and strict validation when artifacts change, and prevent text-only override of unmet prerequisites.
- [x] 2.4 Preserve the project CI/CD boundary and require candidate-SHA-matched pre-merge preview evidence when a criterion depends on deployed candidate behavior.

## 3. Verification

- [x] 3.1 Add unit/coordinator tests for full task/scenario coverage, missing/extra task IDs, unavailable agents/workflows, absent deployment preview, unknown SHA, and no Apply dispatch on blocked assessment.
- [ ] 3.2 Add PostgreSQL/API E2E proving a blocked proposal remains HUMAN_REQUIRED with its evidence, no Apply attempt is consumed, and updated verified capability/request evidence causes a fresh assessment rather than bypassing the gate.
- [x] 3.3 Run focused and relevant regression suites, lint, and strict OpenSpec validation; capture integration evidence against the immutable implementation SHA.
