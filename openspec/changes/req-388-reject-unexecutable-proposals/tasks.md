## 1. Evidence model and assessment

- [x] 1.1 Inventory task, acceptance-scenario, configured-agent, workflow-installation, project-context, and candidate-hash sources used by the existing Propose/complexity path.
- [x] 1.2 Extend the structured thinking assessment to map every validated OpenSpec task and acceptance scenario to its execution stage, responsible actor, capability, dependencies needed before that stage, and observable completion evidence.
- [x] 1.3 Validate task/stage/scenario coverage and verify cited repository paths and configured workflows against the confined candidate; distinguish current-transition blockers from dependencies for later stages.

## 2. Proposal acceptance gate

- [x] 2.1 Persist the feasibility assessment with the exact Request-context and OpenSpec artifact hashes in existing PostgreSQL Run state.
- [x] 2.2 Gate only the next transition whose required dependency is unmet; do not require Apply outputs before Apply or later-stage evidence before its consuming stage, and preserve those later tasks as pending.
- [x] 2.3 Re-evaluate only after authoritative Request or capability evidence changes; require native OpenSpec Update and strict validation when artifacts change, and prevent text-only override of unmet prerequisites.
- [x] 2.4 Preserve the project CI/CD boundary; require candidate-SHA-matched preview evidence only before a stage that explicitly requires pre-merge candidate validation.

## 3. Verification

- [x] 3.1 Add unit/coordinator tests for task-stage coverage, Apply-created outputs, later-stage missing capabilities, true current-transition blockers, unknown SHA, and no dispatch past a blocked transition.
- [x] 3.2 Add PostgreSQL/API E2E proving Apply proceeds when only later-stage work is pending, that the later dependency gates the correct transition, and that changed verified Request/task/capability evidence triggers reassessment without bypassing the gate.
- [x] 3.3 Run focused and relevant regression suites, lint, and strict OpenSpec validation for the stage-aware behavior; capture integration evidence against the immutable implementation SHA.
