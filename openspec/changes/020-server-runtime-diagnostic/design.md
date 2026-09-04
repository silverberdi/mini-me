# Design: 020 Server Runtime Environment Diagnostic

## Architecture & Interfaces

### 1. `StatusService` Enhancement
Extend `src/minime/services/status_service.py`:
```python
import platform
import sys
import os

class StatusService:
    ...
    def get_runtime_environment_diagnostic(self) -> dict[str, Any]:
        """Return server runtime environment facts without secret leakage."""
        return {
            "platform": sys.platform,
            "python_version": platform.python_version(),
            "runtime_mode": "server" if os.path.exists("/etc/minime") else "standalone",
            "database_engine": "PostgreSQL",
        }
```

### 2. Integration into `get_system_status()`
In `get_system_status()`:
```python
return {
    ...
    "runtime_environment": self.get_runtime_environment_diagnostic(),
    ...
}
```

### 3. Verification Strategy
- Add unit tests verifying `get_runtime_environment_diagnostic()` returns expected keys (`platform`, `python_version`, `runtime_mode`, `database_engine`).
- Verify `get_system_status()` includes `runtime_environment`.
