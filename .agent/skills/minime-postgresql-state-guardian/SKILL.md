---
name: minime-postgresql-state-guardian
description: Enforce PostgreSQL-only durable state, SQLAlchemy/Alembic migrations and transactional transition evidence.
---
# PostgreSQL State Guardian
No SQLite compatibility layer. No ad-hoc startup DDL. Use Alembic migrations. Keep domain rules out of ORM models where practical. Current-state transition and corresponding event evidence should be atomic. Runtime DB role is restricted; never embed credentials.
