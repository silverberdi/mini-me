---
name: minime-postgresql-state-guardian
description: Enforce PostgreSQL-only durable state, SQLAlchemy/Alembic migrations and transactional transition evidence.
---
# PostgreSQL State Guardian
No SQLite compatibility layer. No ad-hoc startup DDL. Use Alembic migrations. Keep domain rules out of ORM models where practical. Current-state transition and corresponding event evidence should be atomic. Runtime DB role is restricted; never embed credentials.

For every database-backed project check, use that project's optional `test_database` profile: expected PostgreSQL host, port, isolated test database name, known production database names, and a host environment-variable name ending in `_TEST_DATABASE_URL`. Persist only this non-secret identity and reference. Resolve and compare the URL immediately before the check; never use `MINIME_DATABASE_URL`, an inline URL, a production database, or Mini Me's operational database as a project test target. Inject the resolved credential only into the one check subprocess that declares `uses_test_database: true`; redact it from output and evidence. Test migrations against the designated project test database, never production.
