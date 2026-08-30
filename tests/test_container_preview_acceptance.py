"""End-to-end acceptance tests for Container Preview lifecycle."""

from __future__ import annotations

import os
import shutil

import pytest

from minime.domain.enums import PreviewStatus
from minime.domain.models import PreviewSession
from minime.services.container_preview_service import ContainerPreviewService


def is_docker_daemon_available() -> bool:
    docker_bin = shutil.which("docker") or "/usr/local/bin/docker"
    if not os.path.exists(docker_bin):
        return False
    import subprocess

    try:
        ret = subprocess.run([docker_bin, "info"], capture_output=True, timeout=5)
        return ret.returncode == 0
    except Exception:
        return False


@pytest.mark.asyncio
@pytest.mark.skipif(not is_docker_daemon_available(), reason="Docker daemon not available on host")
async def test_real_container_preview_build_start_probe_and_teardown(tmp_path):
    """Exercise real Docker container build, startup, port allocation, health probe, and teardown."""
    # Create minimal web app in tmp_path
    app_dir = tmp_path / "preview_app"
    app_dir.mkdir()

    server_code = """
import http.server
import socketserver
import json

class HealthHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({'status': 'healthy', 'version': 'preview-013'}).encode('utf-8'))

with socketserver.TCPServer(('', 8787), HealthHandler) as httpd:
    httpd.serve_forever()
"""
    (app_dir / "server.py").write_text(server_code.strip())

    dockerfile_content = """
FROM python:3.11-alpine
WORKDIR /app
COPY server.py .
EXPOSE 8787
CMD ["python", "server.py"]
"""
    (app_dir / "Dockerfile").write_text(dockerfile_content.strip())

    svc = ContainerPreviewService()
    tag = "minime-preview:acceptance-test"

    try:
        # 1. Build image
        image_digest = await svc.build_image(worktree_path=app_dir, tag=tag)
        assert image_digest.startswith("sha256:")

        # 2. Start container
        session = PreviewSession(
            preview_id="prev_acceptance_01",
            project_id="mini-me",
            change_name="013-acceptance",
            head_sha="sha_acceptance_head",
            base_sha="sha_acceptance_base",
            image_digest=image_digest,
        )

        container_id, preview_url, host_port = await svc.start_preview_container(
            preview_session=session,
            image_tag_or_digest=tag,
            internal_port=8787,
        )
        assert container_id
        assert preview_url.startswith("http://127.0.0.1:")
        session.container_id = container_id
        session.preview_url = preview_url
        session.allocated_port = host_port

        # 3. Probe health
        is_healthy = await svc.probe_health(
            preview_url, health_path="/api/v1/health", max_attempts=15, interval_seconds=0.5
        )
        assert is_healthy is True

        # 4. Inspect container
        inspect_res = await svc.inspect_container(container_id)
        assert inspect_res["running"] is True

        # 5. Teardown
        teardown_ok = await svc.teardown_preview(session)
        assert teardown_ok is True
        assert session.status == PreviewStatus.TERMINATED

        # Verify container no longer running
        after_inspect = await svc.inspect_container(container_id)
        assert after_inspect["running"] is False

    finally:
        # Clean up any leftover test containers
        await svc.remove_container_by_name("minime-preview-mini-me-013-acceptance-gen1")
