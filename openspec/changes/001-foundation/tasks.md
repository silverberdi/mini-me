# Tasks

## 1. Project/application foundation
- [ ] 1.1 Create Python 3.12+ package layout, dependency management, settings and structured/redacted logging.
- [ ] 1.2 Define domain IDs/models and interfaces separating domain from persistence/integrations.
- [ ] 1.3 Add FastAPI health/status skeleton and minimal CLI entrypoint.

## 2. PostgreSQL durable state
- [ ] 2.1 Configure PostgreSQL-only SQLAlchemy 2.x persistence using `MINIME_DATABASE_URL`.
- [ ] 2.2 Add Alembic and initial migration for projects, changes, bindings, events and minimum metric/evidence facts.
- [ ] 2.3 Implement transactional current-state + event persistence primitives.
- [ ] 2.4 Add migration/up/down/startup compatibility tests and restart persistence test.

## 3. Project registry and repository binding
- [ ] 3.1 Implement validated project registration/update/read model with immutable project ID.
- [ ] 3.2 Normalize and validate repository remote identity and base branch metadata.
- [ ] 3.3 Enforce Codex↔Antigravity complementary primary role configuration when both are present.
- [ ] 3.4 Add mismatch/duplicate/invalid-config denial tests.

## 4. OpenSpec discovery and readiness
- [ ] 4.1 Implement OpenSpec adapter using structured CLI outputs where available.
- [ ] 4.2 Discover active changes/artifacts under registered projects.
- [ ] 4.3 Implement structured DoR evaluation for Foundation-applicable criteria and roadmap gating.
- [ ] 4.4 Prove runtime status is not written into OpenSpec.

## 5. GitHub work-binding foundation
- [ ] 5.1 Define GitHub integration contracts and durable Issue/Project identifiers without full PR automation.
- [ ] 5.2 Implement/mock binding validation against repository identity.
- [ ] 5.3 Add reconcilable sync-failure state/evidence rather than destructive fallback.

## 6. Status, evidence and acceptance
- [ ] 6.1 Expose projects/changes/readiness reasons via API + CLI.
- [ ] 6.2 Persist correlation/timing facts and verify redaction behavior.
- [ ] 6.3 Add automated acceptance scenarios for every Foundation capability including restart and wrong-repo binding.
- [ ] 6.4 Run `openspec validate --all` and OpenSpec verification workflow; record evidence.
- [ ] 6.5 Update canonical docs/config examples only if implementation reveals a confirmed necessary correction; do not expand scope.
