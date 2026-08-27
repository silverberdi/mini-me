from contextlib import contextmanager
from datetime import UTC, datetime

from minime.cli import main
from minime.domain.enums import ProviderHealthStatus
from minime.domain.models import CapacityWindow, ProviderHealth


def test_providers_health_cli_renders_capacity_reset_without_crashing(monkeypatch, capsys):
    health = ProviderHealth(provider="codex", status=ProviderHealthStatus.EXHAUSTED)
    window = CapacityWindow(provider="codex", capacity_reset_at=datetime(2030, 1, 1, tzinfo=UTC), retry_after_seconds=60)
    class Service:
        def __init__(self, uow): pass
        def list_all_health_with_capacity(self): return [(health, window)]
    @contextmanager
    def session():
        yield object()
    monkeypatch.setattr(main.db_manager, "session", session)
    monkeypatch.setattr(main, "ProviderHealthService", Service)
    main.providers_health_cmd(json_output=False)
    output = capsys.readouterr().out
    assert "Expected Reset: 2030-01-01T00:00:00+00:00" in output
    assert "Retry After: 60s" in output
