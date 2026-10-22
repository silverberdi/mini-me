## 1. Inventory, contracts, and unified project configuration

- [ ] 1.1 Trace every API/CLI/DI, domain, repository, YAML, static-client, test, and database consumer of `Project`, onboarding DTOs, fixed roles, context/backlog/admission fields; record live readers/writers and exact retirement choices in `design.md` Removal Ledger.
- [ ] 1.2 Define validated project create/update/read schemas for type, immutable id/repository identity, branch, separate provider connections, four profiles, budgets/review limits, lifecycle, and truthful onboarding status; reject GREENFIELD before persistence unless a ZIP is present and valid.
- [ ] 1.3 Refactor `ProjectService` and `ProjectOnboardingService` into one project creation/configuration authority; keep repository identity immutable while validating authorized changes to branch, providers and role profiles.
- [ ] 1.4 Implement one authenticated API semantic for project list/get/create/update/activate/pause, catalog, onboarding state and context operations; reconcile old routes to one handler or explicit deprecation without silent legacy execution.
- [ ] 1.5 Implement corresponding `minime project` CLI operations through the same service/contracts, with explicit arguments, sanitized errors and non-zero failure; do not add ticket start or scheduler commands.

## 2. Provider catalog, per-project GitHub connections, and contracts

- [ ] 2.1 Define the minimal provider metadata catalog with distinct `tickets` and `git_pr` responsibilities, required typed fields/auth modes/capabilities, and honest unavailable status for unimplemented providers.
- [ ] 2.2 Separate narrow ticket-source and Git/PR contracts while reusing the existing GitHub App auth, transport, repository identity, error/result and idempotency behavior.
- [ ] 2.3 Implement per-project GitHub Issues and Git/PR connection validation, including different repositories and independently selected auth; keep Issue lifecycle operations available as contracts/configuration only, with ticket selection/execution deferred to F3.
- [ ] 2.4 Support only explicit existing `.env` GitHub App selection or a project-owned GitHub App using validated App/installation identifiers and protected host key-file reference; isolate adapter/token state per project and reject implicit fallback.
- [ ] 2.5 Verify repository identity and actual permissions required for configured read, branch, push and PR operations; ensure insufficient/unknown permission prevents mutation and gives a sanitized actionable reason.
- [ ] 2.6 Add contract/security tests proving catalog contains metadata only, two project auth identities cannot cross-contaminate, project URLs/repositories are separate, ADO is unselectable, and no key/token escapes API/CLI/log/prompt/Git/PR.

## 3. Agent capability catalog and project profiles

- [ ] 3.1 Inventory configured provider adapters, CLI invocation profiles, actual model/effort discovery, native workflow resolver, and repository-installed skills/workflows; update `design.md` census with observed commands/capabilities and consumers.
- [ ] 3.2 Implement a read-only agent capability catalog exposing only verified executables, transports, role/stage capability, file-edit/read-only distinction, models, efforts, skills and native workflow identities.
- [ ] 3.3 Persist four project-scoped profiles (`thinking`, `execution`, `independent_review`, `fallback`) and finite review/correction/spending policy without fixed provider assignments or free-form commands.
- [ ] 3.4 Resolve a selected profile against live/configured model and effort evidence, exact CLI transport and installed per-agent native workflow/skill; preserve Codex and Antigravity syntax differences and block unsupported combinations.
- [ ] 3.5 Reuse the existing OpenSpec Apply identity/evidence boundary and extend only the native capability resolution required for Greenfield; do not add OpenSpec semantic generators, workflow state machines or F3 dispatch.
- [ ] 3.6 Add tests for role compatibility, unsupported text-only providers, missing Verify/workflow, author/reviewer independence, finite limits and disabled/unauthorized paid fallback.

## 4. Durable Greenfield bootstrap through official OpenSpec and GitHub PR

- [ ] 4.1 Implement preflight for operator, project/repository/branch identity, permissions, workspace binding, profile/workflow capability, Node/official OpenSpec prerequisites, ZIP presence and authorized budget before Git/agent effects.
- [ ] 4.2 Use the validated managed workspace, binding, root/worktree guards and current Git/GitHub capabilities to establish or create the requested main branch only when absent and provable; create a distinct bootstrap branch from its recorded base SHA.
- [ ] 4.3 Install/check official OpenSpec CLI and dependencies in the authorized workspace using official setup/configuration; verify all native workflows/skills required by selected agent profiles, including Verify; never generate wrappers or artifacts as a substitute.
- [ ] 4.4 Run the configured real file-capable thinking agent on the exact Greenfield context package, with bounded source-faithful instructions and project-bound workspace identity; retain invocation/workflow/usage evidence and avoid duplicate paid invocation on uncertain result.
- [ ] 4.5 Validate provenance, index links, canonical instruction references, official OpenSpec config, secret scan and bounded expected diff; preserve existing compatible AGENTS/agent instructions and block unresolved overwrite conflicts.
- [ ] 4.6 Commit and push only the bootstrap branch and create one first PR against the configured base; persist exact repository/base/head/PR identity and never write or auto-merge main.
- [ ] 4.7 Expose PR/merge status; observe exact remote merge before setting `PREPARED`, block stale/rejected/unobservable candidates, and prove activation does not begin F3 or start scheduler.

## 5. Secure context ZIP receipt and faithful organization

- [ ] 5.1 Define finite ZIP limits and safe-entry policy from supported host/runtime capabilities; reject traversal, absolute paths, collisions, links/special files, disallowed nesting/executables, oversized archives and secret-bearing inputs before extraction or project creation.
- [ ] 5.2 Extract in a temporary guarded managed workspace without following links or executing archive content; preserve package hash, source filenames and provenance without storing a duplicate archive in PostgreSQL.
- [ ] 5.3 Define and test the thinking-agent organization contract for product facts, requirements/decisions/restrictions/architecture/references/diagrams/assets, source fidelity, canonical index, contradiction register and prohibition on invented content.
- [ ] 5.4 Add bounded references to canonical context in `AGENTS.md`, relevant existing agent instruction equivalents and `openspec/config.yaml` while preserving compatible content; use official OpenSpec validation.
- [ ] 5.5 Verify no secrets, unsupported claims, provenance gaps, broken/out-of-root links, unrelated overwrites, or context masquerading as backlog reaches commit/agent/GitHub.
- [ ] 5.6 Add malicious ZIP, contradiction, symlink/traversal, secret, fidelity/provenance, unresolved-instruction conflict and no-write/no-dispatch negative tests.

## 6. Incremental context package and approval PR

- [ ] 6.1 Accept a new ZIP only for an actually prepared project; bind it to current approved main/base SHA and configured thinking profile; reject project reset or pending unmerged context as a base.
- [ ] 6.2 Reuse the same safe extraction and real thinking-agent fidelity checks to compare new material with approved context, distinguish additions and explicit replacements, preserve prior provenance and surface unresolved contradictions.
- [ ] 6.3 Create a new branch from current main, validate the documentary/config diff, commit/push and publish one new PR; keep approved context pointer unchanged until exact merge observation.
- [ ] 6.4 Reconcile retries by package hash/revision/base/head/PR identity before agent invocation or external mutation; retain unknown effects and avoid duplicate agent charges/PRs.
- [ ] 6.5 Add integration tests for complementary, duplicate, explicit replacement, unapproved contradiction, invalid/empty package, open PR main invariance, merge advancement and lost-response recovery.

## 7. PostgreSQL migration, legacy retirement, and recovery

- [ ] 7.1 Inspect actual Alembic head, PostgreSQL columns/constraints/indexes/FKs/row counts and representative project/binding/auth/budget/evidence rows; confirm no production target and save restorable disposable backup before designing DDL.
- [ ] 7.2 Add a new Alembic revision from the verified head for minimal project type/config/profile/onboarding/PR checkpoint data; preserve durable bindings, auth, budgets, worktree and candidate/audit evidence; conservatively classify unmappable legacy rows as configured/blocked.
- [ ] 7.3 Migrate every retained reader/writer and API/CLI/client reference before removing legacy local backlog/context/admission fields; update only tests exclusive to replaced behavior and preserve security/provider/worktree regression coverage.
- [ ] 7.4 Drop only columns proven unused by static/dynamic caller and FK/data census; preserve F3/F5 gate/deployment fields and historical Alembic files; keep ledger decisions/evidence current in `design.md`.
- [ ] 7.5 Test backup/restore, upgrade, representative data readability, downgrade, re-upgrade and data-preservation behavior on disposable PostgreSQL; do not connect migration checks to production.
- [ ] 7.6 Test restart/retry after workspace, agent, push, PR and merge-observation interruption; confirm binding mismatch, unknown effects and stale candidates block without destructive retry, repeated spend or duplicate PR.

## 8. Verification, end-to-end proof, and closure evidence

- [ ] 8.1 Run Ruff, type/format/static checks configured by the repository, OpenSpec strict validation, focused unit/contract tests and PostgreSQL integration/migration tests after obsolete callers are removed.
- [ ] 8.2 Verify API authentication and CRUD/lifecycle/provider/agent catalogs, CLI success/failure, no secrets in outputs, Greenfield no-ZIP rejection without row/effects, Brownfield configured-only, and no F3 ticket/scheduler/agent execution outside bootstrap.
- [ ] 8.3 Verify the official OpenSpec CLI/commands/skills for each selected agent in an isolated repository and prove missing capability fails closed rather than emulating it.
- [ ] 8.4 Under explicit owner credential/budget policy, execute one real E2E with disposable GitHub repositories and real selected thinking CLI: configure project, ingest authentic ZIP, build branch/official OpenSpec context, create first PR, observe human-approved test merge, add second ZIP, create another PR, prove main/context unchanged until second test merge, and preserve exact SHA/provenance/cost evidence.
- [ ] 8.5 Reconcile every Issue #170 acceptance row against specs, tests and bound E2E evidence; complete the Removal Ledger, inspect final diff for unrelated files/secrets and confirm only `gacela-02-proyectos` planning/implementation scope remains.
