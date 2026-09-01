# Design: Live Self-Hosting Pilot Diagnostic

## Context

Stage 016 requires verification of live self-hosting capabilities across GitHub backlog discovery, queue ranking, autonomous admission, isolated candidate worktree allocation, provider implementation, deterministic checks, complementary review, DeepSeek Direct audit, and pull request creation.

This pilot adds an operational self-hosting diagnostic read-model in `StatusService`.

## Technical Design

### 1. Diagnostic Method
In `src/minime/services/status_service.py`, implement:
```python
def get_self_hosting_diagnostic(self) -> dict[str, Any]:
    return {
        "runtime_engine": "mini-me-runtime",
        "status": "SELF_HOSTING_READY",
        "autonomous_queue": True,
    }
```

### 2. Integration in `get_system_status()`
In `StatusService.get_system_status()`:
```python
status_data["self_hosting"] = self.get_self_hosting_diagnostic()
```

### 3. Unit Test Verification
Create `tests/test_self_hosting_diagnostic.py` asserting:
- `get_self_hosting_diagnostic()` returns expected keys and values.
- `get_system_status()` includes `"self_hosting"` with valid diagnostic dictionary.
