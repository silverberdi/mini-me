"""Tests for the self-hosting runtime diagnostic."""

from minime.services.status_service import StatusService


def test_self_hosting_diagnostic(in_memory_uow):
    service = StatusService(in_memory_uow)

    diagnostic = service.get_self_hosting_diagnostic()

    assert diagnostic == {
        "runtime_engine": "mini-me-runtime",
        "status": "SELF_HOSTING_READY",
        "autonomous_queue": True,
    }


def test_system_status_includes_self_hosting_diagnostic(in_memory_uow):
    service = StatusService(in_memory_uow)

    status_data = service.get_system_status()

    assert status_data["self_hosting"] == {
        "runtime_engine": "mini-me-runtime",
        "status": "SELF_HOSTING_READY",
        "autonomous_queue": True,
    }
