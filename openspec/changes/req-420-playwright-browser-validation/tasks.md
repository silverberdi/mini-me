## 1. Native proposal context and feasibility assignment

- [x] 1.1 Add a bounded, read-only inventory of configured checks and recognized `package.json`, `pyproject.toml`, and `Makefile` test declarations; include the observed Playwright/Chromium capability in the existing feasibility input without persisting a new project metadata record.
- [x] 1.2 Update the existing native-propose feasibility instructions and validation so browser-reproducible UI tasks map to the configured executor in Apply or Verify, while genuine human decisions and physical-device-only follow-ups remain separate.
- [x] 1.3 Add regression coverage proving browser navigation, async UI, viewport, and concurrent-session scenarios are executable without operator tasks, and that genuine human decisions remain human-controlled.

## 2. Project test selection and browser execution

- [x] 2.1 Extend the existing candidate test resolver to honor configured project checks first, then select only recognized test commands declared in supported project manifests, including Playwright scripts and Makefile test targets.
- [x] 2.2 Execute Playwright checks through the existing confined check runner and retain the real command, exit code, output, duration, and exact candidate SHA as evidence.
- [x] 2.3 Add an isolated end-to-end regression that runs a declared Playwright scenario against the served candidate application and verifies the recorded invocation and result are bound to its SHA.

## 3. Base execution browser capability and failure handling

- [ ] 3.1 Provision the supported Playwright Chromium runtime once through the existing Mini Me runtime/release path, and verify the configured execution user can launch it without per-project installation.
- [x] 3.2 Report missing or unusable browser dependencies through the existing `ENVIRONMENT_UNAVAILABLE` path with concrete diagnostics; route failed assertions through the ordinary correction workflow without creating a browser-test `HUMAN_REQUIRED` gate.
- [x] 3.3 Add regression coverage for missing Chromium, browser launch failure, ordinary Playwright assertion failure, and successful recovery, without adding a state, database table, service, or Playwright wrapper.

## 4. Physical-device boundary and final verification

- [x] 4.1 Ensure physical-device-only checks are recorded as post-merge follow-up and cannot block browser-automatable Apply/Verify criteria or be reported as passed without evidence.
- [x] 4.2 Run focused proposal-feasibility, resolver, confined Playwright E2E, and correction-path verification; run strict OpenSpec validation and `git diff --check`.
