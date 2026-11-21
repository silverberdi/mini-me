## 1. Candidate test environment sanitization

- [x] 1.1 Replace the candidate-test denylist with an explicit allowlist of supported OS/toolchain runtime variables; ensure arbitrary inherited host values are excluded.
- [x] 1.2 Use the allowlisted environment in both `ChecksRunner` and the coordinator's direct subprocess path; add validated disposable-PostgreSQL values only after existing database checks, and leave authorized agent invocations unchanged.

## 2. Regression evidence

- [x] 2.1 Run child processes through both candidate-test paths with provider keys, alternate credentials, arbitrary host settings, and runtime variables; prove only allowed runtime and validated project-check settings are present.
- [x] 2.2 Confirm authorized provider-agent setup is unchanged and run focused suites for candidate test resolution, checks execution, process confinement, and orchestration test execution.

## 3. OpenSpec validation

- [x] 3.1 Run strict Change validation and verify the final diff remains within Issue #455's candidate-test environment isolation scope.
