## 1. Project Test Database Configuration

- [x] 1.1 Add a typed optional project test-database profile containing only the expected PostgreSQL host, port, test database name, known production database names, and host environment-variable reference; expose it through project configuration and persistence without accepting or storing secret values.
- [x] 1.2 Add the nullable PostgreSQL/Alembic migration for the project profile and verify existing project records still load and save without acquiring a test-database configuration.

## 2. Safe Check Execution

- [x] 2.1 Update configured database checks to resolve the referenced host variable immediately before execution, validate PostgreSQL scheme and exact configured target, reject Mini Me/production/unsafe destinations, and remove literal-URL and `MINIME_DATABASE_URL` fallback paths.
- [x] 2.2 Pass the resolved URL only to the database check subprocess; verify it is absent from agent input, persisted project/check evidence, logs, and unrelated subprocess environments.
- [x] 2.3 Add focused tests for unset references, invalid schemes, host/port/name mismatches, production and Mini Me targets, successful isolated PostgreSQL access, and failure before spawning any unsafe command.

## 3. Stage and PR-CI Evidence

- [x] 3.1 Update test-task feasibility so configured checks are assigned to the earliest stage that can execute them, while only checks explicitly mapped to a named project CI check remain pending for the implementation PR; missing configuration or missing CI coverage is never classified as a valid deferral.
- [x] 3.2 Extend the existing GitHub integration to observe the explicitly mapped check result for the implementation PR's exact candidate head SHA; retain pending state until success and prevent merge on missing, pending, failed, stale, or unobservable results without asking a human to run an automatable test.
- [x] 3.3 Add regression coverage proving test/check identity and candidate SHA binding, automatic waiting while CI is pending, advancement only on same-SHA success, and fail-closed behavior for failed or unavailable results.

## 4. Agent Instructions and End-to-End Evidence

- [x] 4.1 Update the canonical `.agents/skills/minime-postgresql-state-guardian`, `.agents/skills/minime-real-e2e-proof`, and `.agents/skills/minime-reviewer` skills with the shared test-database configuration, secret handling, stage deferral, and evidence rules; verify that capability provisioning keeps the `.agent/skills/` copies identical without maintaining a second policy source.
- [x] 4.2 Verify the project-profile migration and safe test-database check against Mini Me's designated server test database, capturing the actual command, result, target identity, and candidate SHA without touching production.
  - Evidence on candidate `336da0714690c504545111d2900ea396c1590086`: `ChecksRunner.run(... uses_test_database=True)` executed a read-only PostgreSQL query against `192.168.0.194:5432/minime_test`; `SELECT 1` returned `1`, `current_database()` returned `minime_test`, `alembic_version` returned `req466_project_test_database_profile`, and `information_schema` confirmed `projects.test_database` exists. No production database was accessed.
- [ ] 4.3 Run a real candidate test using an isolated PostgreSQL test database and verify its observable result; exercise the PR CI result path against a real implementation PR/check when available, with exact head-SHA evidence. Keep any unavailable external check pending rather than claiming it passed.
  - Local real-database runner check passed against candidate `336da0714690c504545111d2900ea396c1590086`; implementation PR/check does not exist yet, so its SHA-bound CI result remains pending.
- [x] 4.4 Run native OpenSpec Verify and confirm the reviewer uses the immutable candidate plus actual test/CI evidence, does not treat narrative disclaimers as evidence, and leaves absent or pending test results incomplete.
  - Verification workflow run on candidate `147e5112ea303200506d7db2d5fe9b8a2491c5a4`: strict OpenSpec change validation passed; implementation and four delta specs were reviewed against the candidate and focused tests. Reviewer instructions require exact-SHA command/CI evidence and keep absent or pending CI incomplete; regression tests cover pending, failed, missing, and stale checks. Overall Verify remains incomplete because task 4.3's real implementation-PR check is unavailable until a PR exists.
