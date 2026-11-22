## Why

Project checks do not have a safe, standard way to select their own PostgreSQL test database: they can contain a literal URL or fall back to Mini Me's operational database URL. Agents and reviewers therefore lack reliable evidence about test isolation, and otherwise automatable tests can become human gates. This Change defines safe project test-database access and a narrow, SHA-bound CI path for integration tests that cannot run in the current stage.

## What Changes

- Define a non-secret, per-project test database identity and host environment-variable reference that project checks can use; reject embedded credentials and remove fallback to Mini Me's database URL.
- Validate PostgreSQL type and configured test database identity before starting a check; fail before any database-writing command when configuration is missing, unsafe, production, or Mini Me's own database.
- Make the authorized test database available only to the check subprocess that declares it, without exposing its value to agents, prompts, persisted project configuration, or logs.
- Require Apply and Verify to run tests against the project's configured test database when the check is executable in that stage. Defer only checks that require unavailable, non-reproducible external infrastructure to the project's GitHub Actions check for the same candidate SHA; wait for and evaluate that result before treating the evidence as passed.
- Make proposal feasibility and independent review use the configured test-database path and observed test/CI evidence, rather than creating a human gate for a check that has an authorized automated path or blocking on narrative disclaimers that contradict observable evidence.
- Update the existing PostgreSQL, E2E, and reviewer skills with the same policy; do not create a parallel skill or change project repositories, production databases, or deployment workflows.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deterministic-checks-runner`: bind database-backed checks to a project's named test database through a secret-free reference and subprocess-only credential injection.
- `openspec-native-apply-and-verify`: run available tests at their stage and accept deferred integration evidence only from a successful CI check bound to the candidate SHA.
- `openspec-native-propose`: assess test tasks against the project's configured test environment and authorized stage/CI path without treating Apply deliverables as preconditions or inventing human-only gates.
- `reviewer-execution-contract`: ground review findings in the immutable candidate, observed checks, and their SHA-bound CI results; narrative disclaimers alone are not evidence of a defect or missing test.

## Impact

Affected areas are project/check configuration and validation, `ChecksRunner` and its subprocess environment, Apply/Verify test evidence and PR-check observation, proposal feasibility, reviewer instructions, and the existing `minime-postgresql-state-guardian`, `minime-real-e2e-proof`, and `minime-reviewer` skills. Prefer the existing `Project.checks` JSON configuration and GitHub/check-evidence pathways; add no secret store, scheduler, test orchestrator, deployment capability, or project-specific configuration. No production database, project repository, or external service is to be accessed by this Change.
