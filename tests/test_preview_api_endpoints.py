"""API integration tests for Container Preview & Guided Validation endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from minime.api.app import app, get_uow
from minime.domain.enums import PreviewStatus, ValidationVerdict
from minime.domain.models import PreviewSession, Project, ValidationRun


@pytest.fixture
def mock_uow():
    uow = MagicMock()
    uow.projects = MagicMock()
    uow.preview_sessions = MagicMock()
    uow.validation_runs = MagicMock()
    uow.orchestration_runs = MagicMock()
    uow.events = MagicMock()
    return uow


@pytest.fixture
def client(mock_uow):
    app.dependency_overrides[get_uow] = lambda: mock_uow
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_build_preview_endpoint(client, mock_uow):
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
    )
    mock_uow.projects.get_by_id.return_value = project

    with patch(
        "minime.api.app.ContainerPreviewService.build_image", new_callable=AsyncMock
    ) as mock_build:
        mock_build.return_value = "sha256:112233445566778899"

        res = client.post(
            "/api/v1/previews/build",
            json={
                "project_id": "mini-me",
                "change_name": "013-preview",
                "head_sha": "abc1234",
                "base_sha": "def5678",
                "candidate_generation": 1,
            },
        )

        assert res.status_code == 200
        data = res.json()
        assert data["image_digest"] == "sha256:112233445566778899"
        assert data["status"] == "BUILDING"
        assert mock_uow.preview_sessions.save.called


def test_start_preview_endpoint(client, mock_uow):
    session = PreviewSession(
        preview_id="prev_01",
        project_id="mini-me",
        change_name="013-preview",
        head_sha="abc1234",
        base_sha="def5678",
        image_digest="sha256:112233",
        status=PreviewStatus.BUILDING,
    )
    mock_uow.preview_sessions.get_by_id.return_value = session

    with (
        patch(
            "minime.api.app.ContainerPreviewService.start_preview_container", new_callable=AsyncMock
        ) as mock_start,
        patch(
            "minime.api.app.ContainerPreviewService.probe_health", new_callable=AsyncMock
        ) as mock_probe,
    ):
        mock_start.return_value = ("c12345", "http://127.0.0.1:18787", 18787)
        mock_probe.return_value = True

        res = client.post(
            "/api/v1/previews/start",
            json={"preview_id": "prev_01", "internal_port": 8787, "probe_health": True},
        )

        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "READY"
        assert data["preview_url"] == "http://127.0.0.1:18787"
        assert data["allocated_port"] == 18787


def test_get_preview_session_endpoint(client, mock_uow):
    session = PreviewSession(
        preview_id="prev_01",
        project_id="mini-me",
        change_name="013-preview",
        head_sha="abc1234",
        base_sha="def5678",
        image_digest="sha256:112233",
        status=PreviewStatus.READY,
        preview_url="http://127.0.0.1:18787",
        allocated_port=18787,
    )
    mock_uow.preview_sessions.get_by_id.return_value = session

    res = client.get("/api/v1/previews/prev_01")
    assert res.status_code == 200
    data = res.json()
    assert data["preview_id"] == "prev_01"
    assert data["status"] == "READY"
    assert data["preview_url"] == "http://127.0.0.1:18787"


def test_teardown_preview_endpoint(client, mock_uow):
    session = PreviewSession(
        preview_id="prev_01",
        project_id="mini-me",
        change_name="013-preview",
        head_sha="abc1234",
        base_sha="def5678",
        status=PreviewStatus.READY,
    )
    mock_uow.preview_sessions.get_by_id.return_value = session

    with patch(
        "minime.api.app.ContainerPreviewService.teardown_preview", new_callable=AsyncMock
    ) as mock_teardown:
        mock_teardown.return_value = True
        res = client.post("/api/v1/previews/prev_01/teardown")
        assert res.status_code == 200
        assert res.json()["status"] == "TERMINATED"


def test_validation_submit_endpoint(client, mock_uow):
    res = client.post(
        "/api/v1/validations/submit",
        json={
            "project_id": "mini-me",
            "change_name": "013-preview",
            "head_sha": "abc1234",
            "base_sha": "def5678",
            "image_digest": "sha256:112233",
            "verdict": "PASS",
            "scenario_results": [{"scenario_id": "sc_01", "verdict": "PASS"}],
            "notes": "Verified visual appearance",
            "operator": "operator_bob",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["verdict"] == "PASS"
    assert data["head_sha"] == "abc1234"
    assert mock_uow.validation_runs.save.called
    assert mock_uow.events.save.called


def test_validation_authority_endpoint(client, mock_uow):
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
    )
    mock_uow.projects.get_by_id.return_value = project

    val = ValidationRun(
        validation_id="val_01",
        project_id="mini-me",
        change_name="013-preview",
        head_sha="abc1234",
        base_sha="def5678",
        image_digest="sha256:112233",
        verdict=ValidationVerdict.PASS,
    )
    mock_uow.validation_runs.get_latest_for_candidate.return_value = val

    res = client.get(
        "/api/v1/validations/authority/mini-me/013-preview",
        params={
            "head_sha": "abc1234",
            "base_sha": "def5678",
            "image_digest": "sha256:112233",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_authorized"] is True
    assert data["is_stale"] is False
    assert data["latest_verdict"] == "PASS"
