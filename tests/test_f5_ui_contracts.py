"""F5 UI contracts: explicit shell routes and live module graph."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.conftest import InMemoryPersistenceUnitOfWork

from minime.api.app import app, get_uow


@pytest.fixture
def client():
    uow = InMemoryPersistenceUnitOfWork()
    app.dependency_overrides[get_uow] = lambda: uow
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_five_shell_routes_are_explicit_and_share_one_document(client: TestClient) -> None:
    for route in ("/", "/dashboard", "/trabajo", "/trabajo-actual", "/proyectos", "/backlog"):
        response = client.get(route)
        assert response.status_code == 200
        assert 'src="/static/js/app.js"' in response.text or 'app-root' in response.text
    assert client.get("/not-a-shell-route").status_code == 404
    assert client.get("/api/v1/orchestration/runs").status_code != 410


def test_f5_client_has_no_operational_persistence_or_optimistic_transition() -> None:
    static = Path(__file__).parents[1] / "src" / "minime" / "static"
    source = "\n".join((static / "js" / name).read_text(encoding="utf-8") for name in ("app.js", "client.js", "refresh.js", "views.js"))
    assert "localStorage" in (static / "js" / "app.js").read_text(encoding="utf-8")  # theme only
    assert "localStorage.setItem(\"minime-theme\"" in source
    assert "operator_clarification" in source
    assert "setInterval" in source
    assert "innerHTML" not in source
    assert "optimistic" not in source.lower()
