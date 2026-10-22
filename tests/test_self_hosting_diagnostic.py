"""Unit tests for self-hosting pilot diagnostic in status service."""

from unittest.mock import MagicMock

from minime.services.status_service import StatusService


def test_get_self_hosting_diagnostic():
    uow = MagicMock()
    service = StatusService(uow)
    diagnostic = service.get_self_hosting_diagnostic()

    assert isinstance(diagnostic, dict)
    assert diagnostic["runtime_engine"] is None
    assert diagnostic["status"] == "UNAVAILABLE_IN_F1"
    assert diagnostic["autonomous_queue"] is False


def test_get_system_status_includes_self_hosting():
    uow = MagicMock()
    uow.projects.list_all.return_value = []
    uow.events.list_events.return_value = []

    service = StatusService(uow)
    status = service.get_system_status()

    assert "self_hosting" in status
    assert status["self_hosting"]["status"] == "UNAVAILABLE_IN_F1"
