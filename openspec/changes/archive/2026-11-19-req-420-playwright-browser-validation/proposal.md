## Why

Runs currently turn browser-reproducible UI checks into operator work or human gates, even though the configured executor can run Playwright against the candidate. This slows delivery and can make otherwise executable Changes appear infeasible; the Issue asks Mini Me to keep browser checks in Apply/Verify and reserve post-merge follow-up for checks that truly need physical hardware.

## What Changes

- Give the native proposal and feasibility assessment the repository's observed test commands and browser tooling before it assigns work; keep proposal/spec authoring inside the official OpenSpec workflow.
- Require browser-reproducible UI acceptance scenarios to be expressed as executor-owned Playwright work in Apply/Verify, with command, result, output, and candidate SHA evidence. They must not become operator tasks or `HUMAN_REQUIRED` gates.
- Reuse declared repository runners and scripts from existing manifests/configuration; provision one supported Chromium/Playwright runtime through Mini Me's existing runtime/release path and make its availability observable, without per-project installer orchestration, database metadata, services, or a Mini Me Playwright wrapper.
- Send failed tests through the existing correction path. Report unavailable browser/runtime dependencies as an evidence-backed technical environment blocker, not as a request for the operator to run the test.
- Keep device-only checks explicitly post-merge and separate from automated browser acceptance; do not claim physical checks passed without evidence.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `openspec-native-propose`: provide observed project tooling to the native proposal/feasibility workflow and require browser-reproducible checks to be assigned to the executor rather than the operator.
- `openspec-native-apply-and-verify`: run project-declared Playwright/browser checks as ordinary Apply/Verify work, preserve observable result and candidate identity evidence, and keep physical-device checks post-merge.
- `blocker-validation-and-continuation`: route browser-test failures through existing correction behavior and missing browser runtime capability to the existing technical environment-blocker path, without a human test gate.

## Impact

Expected touch points are the existing proposal feasibility assessment and its prompt/context, task-stage assignment, candidate test discovery/execution, existing validation/blocker outcomes, and a small idempotent browser provision/check in Mini Me's existing runtime/release path. No API, database schema, microservice, package manager, OpenSpec workflow implementation, or project business logic is added. This authorizes changing release automation but does not authorize running a deployment. The configured agent still executes native OpenSpec; Mini Me supplies verified repository/runtime facts and evaluates evidence.
