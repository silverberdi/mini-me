# Spec: server-runtime-diagnostic

## ADDED Requirements

### Requirement 1: Runtime Environment Diagnostic Method
The `StatusService` MUST provide a `get_runtime_environment_diagnostic()` method returning a dictionary with `platform`, `python_version`, `runtime_mode`, and `database_engine`.

#### Scenario 1: Retrieve runtime diagnostic
- **WHEN** `get_runtime_environment_diagnostic()` is called on `StatusService`
- **THEN** it returns a dictionary containing:
  - `platform` as a non-empty string (e.g. `linux`, `darwin`)
  - `python_version` as a valid Python version string (e.g. `3.14.5`)
  - `runtime_mode` as either `"server"` or `"standalone"`
  - `database_engine` as `"PostgreSQL"`

### Requirement 2: System Status Integration
The `StatusService.get_system_status()` method MUST include the `runtime_environment` dictionary in its top-level return object.

#### Scenario 2: System status payload contains runtime_environment
- **WHEN** `get_system_status()` is called on `StatusService`
- **THEN** the returned dictionary includes a key `"runtime_environment"` matching `get_runtime_environment_diagnostic()`.
