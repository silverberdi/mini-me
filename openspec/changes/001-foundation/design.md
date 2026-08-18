# Design

## Architecture
Create a modular Python application with clear domain, persistence, integration and API/CLI boundaries. Do not couple domain rules directly to GitHub/OpenSpec/SQLAlchemy clients.

## Persistence
PostgreSQL is the sole runtime database. SQLAlchemy 2.x models/repositories and Alembic versioned migrations are mandatory. Store current entity state plus append-only domain/operational events. Avoid event sourcing as a requirement; event history is auditability/recomputation evidence, while current state remains directly queryable.

## Project identity
Use an immutable internal project identifier independent of display name. Persist canonical GitHub repository owner/name (and normalized remote identity). Project registration validates repository path/remote where available.

## Work binding
A discovered executable change must eventually bind one project, one repository, one GitHub Issue and one OpenSpec change. Foundation may allow a discovered record to remain incomplete/non-READY, but readiness must explain missing/invalid bindings structurally.

## OpenSpec
Use OpenSpec CLI JSON-capable commands when appropriate rather than parsing human terminal output. Runtime data never writes quota/retry/provider status into OpenSpec.

## GitHub
Foundation defines adapter/contracts and durable mapping identifiers. It may use fakes/mocks for automated tests; live GitHub setup is opt-in. Do not build full PR workflow early.

## State/events
Centralize allowed domain transitions. Persist current state and corresponding event atomically in one DB transaction where feasible.

## Security
Secrets from environment/protected host paths only. Tests must prove secrets are not required in repository config. No admin PostgreSQL credentials in daemon runtime.

## Observability
Use structured logging with correlation/project/change identifiers and redaction. Persist enough timestamps/facts for later lead/cycle/attempt metrics.

## Failure behavior
Invalid repository binding/OpenSpec structure/config is visible and blocks READY rather than being guessed around.
