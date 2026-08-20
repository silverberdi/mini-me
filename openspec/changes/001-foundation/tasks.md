# Tasks

## 1. Project/application foundation
- [x] 1.1 Create Python 3.12+ package layout, dependency management, settings and structured/redacted logging.
- [x] 1.2 Define domain IDs/models and interfaces separating domain from persistence/integrations.
- [x] 1.3 Add FastAPI health/status skeleton and minimal CLI entrypoint.

## 2. PostgreSQL durable state
- [x] 2.1 Configure PostgreSQL-only SQLAlchemy 2.x persistence using `MINIME_DATABASE_URL`.
- [x] 2.2 Add Alembic and initial migration for projects, changes, bindings, events and minimum metric/evidence facts.
- [x] 2.3 Implement transactional current-state + event persistence primitives.
- [x] 2.4 Add migration/up/down/startup compatibility tests and restart persistence test.

## 3. Project registry and repository binding
- [x] 3.1 Implement validated project registration/update/read model with immutable project ID.
- [x] 3.2 Normalize and validate repository remote identity and base branch metadata.
- [x] 3.3 Enforce Codex↔Antigravity complementary primary role configuration when both are present.
- [x] 3.4 Add mismatch/duplicate/invalid-config denial tests.

## 4. OpenSpec discovery and readiness
- [x] 4.1 Implement OpenSpec adapter using structured CLI outputs where available.
- [x] 4.2 Discover active changes/artifacts under registered projects.
- [x] 4.3 Implement structured DoR evaluation for Foundation-applicable criteria and roadmap gating.
- [x] 4.4 Prove runtime status is not written into OpenSpec.

## 5. GitHub work-binding foundation
- [x] 5.1 Define GitHub integration contracts and durable Issue/Project identifiers without full PR automation.
- [x] 5.2 Implement/mock binding validation against repository identity.
- [x] 5.3 Add reconcilable sync-failure state/evidence rather than destructive fallback.

## 6. Status, evidence and acceptance
- [x] 6.1 Expose projects/changes/readiness reasons via API + CLI.
- [x] 6.2 Persist correlation/timing facts and verify redaction behavior.
- [x] 6.3 Add automated acceptance scenarios for every Foundation capability including restart and wrong-repo binding.
- [x] 6.4 Run `openspec validate --all` and OpenSpec verification workflow; record evidence.
- [x] 6.5 Update canonical docs/config examples only if implementation reveals a confirmed necessary correction; do not expand scope.
