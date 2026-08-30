"""Unit tests for ContainerPreviewService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from minime.domain.enums import PreviewStatus
from minime.domain.models import PreviewSession
from minime.services.container_preview_service import (
    ContainerPreviewService,
    DatabaseSafetyViolationError,
)


@pytest.fixture
def mock_uow():
    uow = MagicMock()
    uow.preview_sessions = MagicMock()
    uow.events = MagicMock()
    return uow


def test_sanitize_text_redacts_secrets_and_tokens():
    svc = ContainerPreviewService()
    secret_text = "Bearer ghp_1234567890abcdef1234567890 sk-1234567890abcdef1234567890 postgresql://user:secretpw@localhost:5432/minime"
    sanitized = svc._sanitize_text(secret_text)
    assert "ghp_" not in sanitized
    assert "secretpw" not in sanitized
    assert "sk-" not in sanitized
    assert "[REDACTED" in sanitized


def test_validate_db_safety_rejects_canonical_minime_database(monkeypatch):
    monkeypatch.setenv("MINIME_DATABASE_URL", "postgresql://user:pass@localhost:5432/minime")
    svc = ContainerPreviewService()

    # Reject same canonical URL
    with pytest.raises(DatabaseSafetyViolationError, match="canonical production database URL"):
        svc._validate_db_safety(
            {"MINIME_DATABASE_URL": "postgresql://user:pass@localhost:5432/minime"}
        )

    # Reject expected_database minime
    with pytest.raises(DatabaseSafetyViolationError, match="cannot target production database"):
        svc._validate_db_safety({"MINIME_EXPECTED_DATABASE": "minime"})


def test_allocate_port_finds_open_port():
    svc = ContainerPreviewService()
    port = svc.allocate_port(min_port=18500, max_port=18600)
    assert 18500 <= port <= 18600


@pytest.mark.asyncio
async def test_build_image_executes_docker_build_and_inspects_digest(mock_uow, tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM alpine:latest\nCMD ['echo', 'hello']")

    svc = ContainerPreviewService(uow=mock_uow)

    async def mock_run_cmd(args, cwd=None, timeout_seconds=120.0):
        if args[0] == "build":
            return 0, "Successfully built image", ""
        elif args[0] == "inspect":
            return (
                0,
                "sha256:112233445566778899aabbccddeeff00112233445566778899aabbccddeeff00\n",
                "",
            )
        return 0, "", ""

    svc._run_docker_cmd = AsyncMock(side_effect=mock_run_cmd)

    digest = await svc.build_image(worktree_path=tmp_path, tag="minime-preview:test")
    assert digest.startswith("sha256:112233445566")
    assert svc._run_docker_cmd.call_count == 2


@pytest.mark.asyncio
async def test_start_preview_container_assigns_labels_and_ports(mock_uow):
    svc = ContainerPreviewService(uow=mock_uow)
    svc.remove_container_by_name = AsyncMock(return_value=True)
    svc._run_docker_cmd = AsyncMock(return_value=(0, "c1234567890abcdef\n", ""))

    session = PreviewSession(
        preview_id="prev_01",
        project_id="mini-me",
        change_name="013-preview",
        head_sha="abc1234",
        base_sha="def5678",
        image_digest="sha256:112233",
        allocated_port=18787,
    )

    container_id, url, port = await svc.start_preview_container(
        preview_session=session,
        image_tag_or_digest="sha256:112233",
        internal_port=8787,
        env_vars={"PORT": "8787"},
    )

    assert container_id == "c1234567890abcdef"
    assert url == "http://127.0.0.1:18787"
    assert port == 18787

    # Verify run args include required labels
    run_args = svc._run_docker_cmd.call_args[0][0]
    assert "app=minime-preview" in run_args
    assert "minime_preview_id=prev_01" in run_args


@pytest.mark.asyncio
async def test_probe_health_returns_true_on_success():
    svc = ContainerPreviewService()
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        success = await svc.probe_health(
            "http://127.0.0.1:18787", max_attempts=2, interval_seconds=0.01
        )
        assert success is True


@pytest.mark.asyncio
async def test_teardown_preview_terminates_and_emits_event(mock_uow):
    svc = ContainerPreviewService(uow=mock_uow)
    svc.stop_container = AsyncMock(return_value=True)
    svc.remove_container_by_name = AsyncMock(return_value=True)

    session = PreviewSession(
        preview_id="prev_01",
        project_id="mini-me",
        change_name="013-preview",
        head_sha="abc1234",
        base_sha="def5678",
        container_id="c12345",
        status=PreviewStatus.READY,
    )

    result = await svc.teardown_preview(session)
    assert result is True
    assert session.status == PreviewStatus.TERMINATED
    assert session.terminated_at is not None
    assert mock_uow.preview_sessions.save.called
    assert mock_uow.events.save.called
    assert mock_uow.commit.called


@pytest.mark.asyncio
async def test_reconcile_orphan_previews_prunes_only_untracked_minime_containers(mock_uow):
    svc = ContainerPreviewService(uow=mock_uow)
    # Return 2 containers: one active in DB, one orphan
    ps_output = "c_active12345\tminime-preview-active\tapp=minime-preview\nc_orphan12345\tminime-preview-orphan\tapp=minime-preview\nforeign_c\tforeign_app\tother_label\n"
    svc._run_docker_cmd = AsyncMock(return_value=(0, ps_output, ""))
    svc.remove_container_by_name = AsyncMock(return_value=True)

    active_sess = PreviewSession(
        preview_id="prev_active",
        project_id="mini-me",
        change_name="013-preview",
        container_id="c_active12345",
        container_name="minime-preview-active",
        head_sha="abc",
        base_sha="def",
        status=PreviewStatus.READY,
    )
    mock_uow.preview_sessions.list_active.return_value = [active_sess]

    cleaned = await svc.reconcile_orphan_previews()
    assert "minime-preview-orphan" in cleaned
    assert "minime-preview-active" not in cleaned
    assert "foreign_app" not in cleaned
