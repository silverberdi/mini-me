## 1. Durable Control Plane reassignment

- [x] 1.1 Make REASSIGN persist the selected linked-Job executor under the canonical run claim and keep it separate from CONTINUE/provider execution.
- [x] 1.2 Make recovery and pipeline executor selection honor a newer successful operator reassignment over older pending automatic handoffs.
- [x] 1.3 Preserve provider health/capacity and reassignment anti-loop gates; do not reset historical counters or same-SHA evidence.
- [x] 1.4 Add integrated positive and negative REASSIGN→CONTINUE tests for the same Run/Job and runner selection.

## 2. Confined Antigravity authentication

- [x] 2.1 Add private, exact-file Antigravity credential projection using the existing confinement lifecycle.
- [x] 2.2 Use the same safe projection in implementer and reviewer runners; detect rotation and redact outputs.
- [x] 2.3 Add real Bubblewrap tests for auth projection, mount isolation, cleanup, and fail-closed behavior. (Added; Linux-only tests are not executable in this macOS environment.)
- [ ] 2.4 Prove `agy models` authentication in Bubblewrap without inference, or document the environment as an explicit blocker.

## 3. Validation and delivery

- [x] 3.1 Run focused and adjacent tests, Ruff, strict OpenSpec validation, and `git diff --check`; record baseline-equivalent macOS sandbox failures and Linux-only skips.
- [ ] 3.2 Create one hotfix PR and document the exact human CONTINUE procedure for the existing N01 Run/Job.
