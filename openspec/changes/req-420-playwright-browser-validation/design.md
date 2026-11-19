## Context

See proposal.md and the four delta specs. The native propose workflow is already resolved and invoked through `AgentRunner`; `_assess_complexity` supplies the evidence-backed feasibility prompt, and `ProposalFeasibilityEvaluator` validates task actors and stages. `CandidateTestResolver` currently honors configured checks, then uses fixed `npm test`/pytest/Rust/Go conventions; it does not inspect declared Playwright scripts or Makefile targets. `ChecksRunner` already records command, exit code, output, duration, and candidate SHA, and recognizes missing executables as `ENVIRONMENT_UNAVAILABLE`.

The PR CI installs Chromium for its own E2E job. The release workflow deploys to the existing self-hosted Linux host, while the repository has no Docker image or per-project browser bootstrap. The execution capability therefore belongs to the existing Mini Me host runtime, not project onboarding. No database migration is needed.

## Goals / Non-Goals

**Goals:** Use existing project test declarations and current feasibility/check paths to assign, execute, and evidence Playwright checks; make the configured executor runtime's browser availability observable; keep device-only follow-up outside the automated gate.

**Non-Goals:** Implement OpenSpec workflows, add a Mini Me browser service/wrapper, create a new task classifier, add tables or durable onboarding metadata, install dependencies separately for each project, or change application business logic.

## Decisions

1. **Enrich the existing native-propose assessment input, not OpenSpec artifacts.** Add a bounded read-only inventory of configured checks, test scripts/targets in `package.json`, `pyproject.toml`, and `Makefile`, and the browser capability observed in the configured execution environment. Pass those facts to the existing assessment prompt. The agent remains the author and operator of the installed native OpenSpec Propose workflow; mini me neither writes nor edits proposal/spec/task artifacts.

2. **Keep task assignment in the existing `actor` and `execution_stage` contract.** Instruct the existing feasibility assessment that browser-reproducible UI checks belong to the configured executor in Apply or Verify. Validate that mapping with the existing report evaluator. Do not add a second scenario-classification engine, new task metadata table, or a new retry/gate state. Actual human decisions remain human; physical-only device checks are explicitly post-merge and do not block browser-verifiable acceptance.

3. **Extend the existing test resolver and checks runner.** Preserve `project.checks` as highest priority; otherwise read only recognized, declared test entry points and select their existing commands, including declared Playwright and Makefile test targets. Do not run scripts during inventory or invent package dependencies. Execute the selected project command through the existing confined `ChecksRunner`; retain its current evidence format and candidate SHA. A Playwright assertion failure is an ordinary failed check for the existing correction path.

4. **Provision one browser for the existing execution host.** Add the smallest idempotent provision/health check to the existing release/runtime path so the configured execution user can launch the supported Playwright Chromium browser. Keep the existing CI browser setup for CI's own suite. Do not add project onboarding installation, per-ticket network downloads, a new container, or a separate browser manager. At runtime, report missing/unlaunchable Chromium through the existing `ENVIRONMENT_UNAVAILABLE` path with the concrete command/capability evidence; do not produce a human test request.

5. **Do not revive retired validation persistence.** Playwright evidence stays in the existing check/evidence records and candidate identity flow. The retired validation-run repository is not reactivated and no database schema changes are introduced.

## Risks / Trade-offs

- **Host package or browser download is unavailable during provisioning** → the release/runtime check fails with its concrete diagnostic; runtime tests do not silently download a browser per project or claim success.
- **A repository has a custom test target not covered by the bounded inventory** → continue to honor its existing `project.checks`; report unsupported declarations accurately instead of guessing or executing arbitrary discovery scripts.
- **A UI criterion is incorrectly assigned to a human** → cover representative navigation, async-state, responsive-viewport, and concurrent-session scenarios in feasibility tests; preserve genuine decision and physical-device gates.
- **Playwright uses candidate-local dependencies inside confinement** → prove the real browser process can launch under the existing confinement and workspace policy; do not weaken network, filesystem, or secret boundaries to make the test pass.

## Migration Plan

No database migration. Update the existing resolver/assessment/check paths and existing release/runtime provisioning only. Roll back by reverting the workflow and code changes; the existing task/check evidence and project configuration remain readable.
