## Context

See `proposal.md` for the problem and scope. `ProjectModel.checks` is currently untyped JSON; checks may carry a database URL directly, and `ChecksRunner` may fall back to the host's `MINIME_DATABASE_URL`. Candidate test environments otherwise use an allowlist. GitHub integration can create and inspect PRs, but the current PR detail payload does not expose check runs by head SHA.

## Goals / Non-Goals

**Goals:** give each database-using project a clear non-secret test target; inject only its resolved credential into the check process that needs it; make test and reviewer evidence observable and SHA-bound; let Apply/Verify proceed when a required integration test has a real, configured PR-CI path, while holding merge until that exact check passes.

**Non-Goals:** provisioning databases or granting server access; executing tests against production or Mini Me's database; changing managed project repositories or their deployment pipelines; changing the native OpenSpec lifecycle or adding a new human approval; building a general test orchestration framework.

## Decisions

1. **Add a typed, optional project test-database profile, not credentials in `checks`.** Extend the existing project configuration/domain and `ProjectModel` with safe metadata for the PostgreSQL test database: its expected database name, expected host/port, known production database names, and the name of the host environment variable holding its URL. Persist only this metadata. Use an additive nullable JSON field and Alembic migration so existing projects remain readable and projects without a database need no dummy configuration. The project API accepts only this shape; a URL, password, or credential value in a project payload is rejected. Existing `checks` continue to own commands, declare whether they use the profile, and, when eligible for deferral, identify the exact PR CI check name.

   Alternative considered: retain a `database_url` value on each check. Rejected because it duplicates project configuration and persists or exposes credentials. A fallback to `MINIME_DATABASE_URL` is also rejected because that URL belongs to Mini Me.

2. **Resolve and validate the target immediately before each database check.** The check runner reads the named environment variable from the host process, parses it without logging it, and compares PostgreSQL scheme, host, port, and database name to the configured test identity. It rejects an unset reference, embedded/non-PostgreSQL target, mismatch, Mini Me database identity, or any configured production database identity before spawning the command. It never falls back to an ambient variable. The resolved URL is added only to that check's child environment; no agent process, prompt, persisted result, or diagnostic receives the value. The test database credential must be scoped to that isolated database, because candidate test code necessarily can use the credential it receives.

   Alternative considered: a suffix denylist or checking only that the database is not named `minime`. Rejected because neither identifies the configured target reliably.

3. **Reuse deterministic checks for execution and evidence; do not add a second test runner.** The existing `project.checks` commands remain the single configured path. Apply/Verify first execute the selected checks that the current environment can run, preserving actual command/result/SHA evidence. A check is deferrable only when the proposal identifies the exact existing GitHub Actions check that runs the same test against an isolated test database. Missing credentials/configuration or an unsafe target is not an external-infrastructure deferral.

4. **Observe the PR check on its exact head SHA before recording deferred evidence or merging.** Extend the existing GitHub adapter path to read the configured check run for the implementation PR's head commit, and bind each deferred test to its explicit check name and candidate SHA. Keep deferred tasks pending through Apply/Verify and PR creation; complete them only after a conclusive successful result for that SHA. A missing, pending, failed, or unobservable check never counts as success. Reuse the current PR and merge lifecycle; do not add a polling service, queue, or deployment behavior. If the result is not yet conclusive, the existing run remains observably waiting and the normal coordinator retry path observes it again without asking a human to run the test.

   Alternative considered: treating an attempted PR merge or generic green CI as sufficient. Rejected because it does not identify which test ran or prove that result belongs to the candidate SHA.

5. **Update existing skills at their established paths.** Extend the canonical `.agents/skills/minime-postgresql-state-guardian/SKILL.md`, `.agents/skills/minime-real-e2e-proof/SKILL.md`, and `.agents/skills/minime-reviewer/SKILL.md`. The existing capability provisioner must keep the `.agent/skills/` copies it creates byte-identical for Antigravity; edit one canonical source and verify provisioned parity instead of authoring two policy copies. They will describe the same test DB profile, no-secret rule, allowed stage-specific test path, and evidence rules. No new skill, copied OpenSpec workflow, or duplicated policy document is introduced.

6. **Review only observable facts.** The reviewer receives the immutable candidate identity and actual check/CI evidence. A narrative disclaimer without contradictory repository or check evidence is not itself a defect; a missing result remains missing and a pending deferred test remains pending. This changes only reviewer evidence handling, not review authority or the rule that review is independent when required by complexity.

## Risks / Trade-offs

- [A project can point its configured test reference at an unintended database] → Require an exact configured host, port, and database identity; reject configured production database names and Mini Me identities; use a test-only database role; fail before spawning on any mismatch.
- [Test code can read the credential passed to its process] → Limit injection to the single test subprocess and require the credential to have access only to the isolated test database; redact captured output and never pass the URL to an agent.
- [A GitHub result can be stale or refer to another commit] → Query checks using the PR's observed head SHA and accept only the configured check's conclusive success for the candidate SHA.
- [Legacy projects have no test DB profile] → Preserve loading and non-database checks; database checks without a safe profile fail with a precise configuration diagnostic before any write.

## Migration Plan

Add the nullable project metadata with an Alembic migration and default existing projects to no test-database profile. Existing non-database checks continue unchanged; legacy database checks using literal URLs or the Mini Me fallback must be converted to a safe profile before they can run. Roll back by removing the new configuration/API field and migration only after any configured profiles are removed; never rewrite or inspect production database contents as part of migration or rollback.
