# Proposal: 020 Server Runtime Environment Diagnostic

## 1. Problem Statement
The mini me operator status and dashboard require operational insight into the underlying server environment (such as host OS platform, Python runtime version, runtime deployment mode, and database dialect) without exposing credentials or secrets.

## 2. Proposed Solution
1. Add `get_runtime_environment_diagnostic()` method to `StatusService` returning structured environment metadata:
   - `platform`: `sys.platform`
   - `python_version`: `platform.python_version()`
   - `runtime_mode`: `"server"` if `/etc/minime` exists, else `"standalone"`
   - `database_engine`: `"PostgreSQL"`
2. Extend `StatusService.get_system_status()` to include `"runtime_environment"`.
3. Add comprehensive test coverage in `tests/test_status_observability.py`.

## 3. Scope and Boundaries
- NON-UI change.
- No schema or Alembic migration required.
- No external provider credential modification.
- Single bounded implementation attempt.
