## Why

Candidate tests currently inherit most of the Mini Me host process environment. On a developer machine or production host this can expose real AI-provider credentials to untrusted candidate code, make missing-configuration tests pass incorrectly, and allow accidental paid API calls. Issue #455 asks to isolate test subprocesses while leaving authorized Mini Me agent invocations unchanged.

## What Changes

- Build every candidate test subprocess environment from an explicit runtime allowlist; do not copy arbitrary host variables into it.
- Preserve the runtime variables needed by supported toolchains and add only project-check values explicitly supported by current configuration after their existing validation.
- Add regression coverage proving host provider keys are absent and required runtime/project-check environment remains available.
- Keep the change confined to candidate test execution; do not change the environment supplied to configured thinking, execution, or review agents.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deterministic-checks-runner`: candidate test subprocesses must not inherit AI-provider credentials from the Mini Me host.

## Impact

Affected areas: `CandidateTestResolver`-selected test paths, `ChecksRunner`, the direct test subprocess path in `NativeOrchestrationCoordinator`, the existing process-environment boundary in `AgentProcessConfinement`, and their regression tests. No public API, provider invocation, deployment workflow, or project configuration schema change is intended. Current explicit project-check environment support remains limited to the existing validated disposable-PostgreSQL settings; this change does not add a general environment-variable configuration feature.
