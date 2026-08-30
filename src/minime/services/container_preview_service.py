"""Container preview runtime service for mini me.

Coordinates candidate-bound container image builds, isolated container lifecycle,
health probing, idempotent teardown, and orphan recovery.
"""

from __future__ import annotations

import asyncio
import os
import re
import socket
from pathlib import Path
from typing import Any

import httpx

from minime.config import AppConfig, get_secret_patterns, load_config
from minime.domain.enums import EventType, PreviewStatus
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import Event, PreviewSession, utc_now
from minime.logging import get_logger

logger = get_logger("services.container_preview")


class DatabaseSafetyViolationError(ValueError):
    """Raised when an unsafe database configuration is supplied to a preview container."""

    pass


class ContainerRuntimeError(RuntimeError):
    """Raised when a container runtime command fails."""

    pass


class ContainerPreviewService:
    """Manages candidate-bound Docker preview containers and health probing."""

    def __init__(
        self,
        uow: PersistenceUnitOfWork | None = None,
        config: AppConfig | None = None,
        docker_cmd: str = "docker",
    ):
        self.uow = uow
        self.config = config or load_config()
        if docker_cmd == "docker":
            import shutil

            resolved = shutil.which("docker")
            if not resolved:
                for candidate in [
                    "/usr/local/bin/docker",
                    "/opt/homebrew/bin/docker",
                    "/Applications/Docker.app/Contents/Resources/bin/docker",
                ]:
                    if Path(candidate).exists():
                        resolved = candidate
                        break
            docker_cmd = resolved or "docker"
        self.docker_cmd = docker_cmd

    def _sanitize_text(self, text: str) -> str:
        """Sanitize secret values and tokens from diagnostics and logs."""
        if not text:
            return ""
        sanitized = text
        for secret in get_secret_patterns():
            if secret and len(secret) >= 4:
                sanitized = sanitized.replace(secret, "[REDACTED]")
        # Sanitize generic token patterns
        sanitized = re.sub(
            r"(ghp|gho|ghs|github_pat)_[a-zA-Z0-9_]{10,}", "[REDACTED_TOKEN]", sanitized
        )
        sanitized = re.sub(r"(sk-[a-zA-Z0-9_-]{10,})", "[REDACTED_API_KEY]", sanitized)
        sanitized = re.sub(
            r"postgresql(\+[^:]+)?://[^:]+:[^@]+@",
            "postgresql://[REDACTED_USER]:[REDACTED_PW]@",
            sanitized,
        )
        return sanitized

    def _validate_db_safety(self, env_vars: dict[str, str] | None) -> None:
        """Verify that preview environment does not point to canonical production database."""
        if not env_vars:
            return
        canonical_db_url = os.environ.get("MINIME_DATABASE_URL", "")
        db_url = env_vars.get("MINIME_DATABASE_URL", "")
        expected_db = env_vars.get("MINIME_EXPECTED_DATABASE", "")

        if canonical_db_url and db_url == canonical_db_url:
            raise DatabaseSafetyViolationError(
                "Preview container attempted to bind to the canonical production database URL."
            )

        if expected_db.lower() in {"minime", "production", "prod"}:
            raise DatabaseSafetyViolationError(
                f"Preview container cannot target production database '{expected_db}'."
            )

    def allocate_port(self, min_port: int = 18000, max_port: int = 19000) -> int:
        """Allocate an available TCP port for a preview container."""
        # Find an open socket port
        for port in range(min_port, max_port):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    s.bind(("127.0.0.1", port))
                    return port
                except OSError:
                    continue
        # Fallback to OS assigned port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    async def _run_docker_cmd(
        self,
        args: list[str],
        cwd: str | Path | None = None,
        timeout_seconds: float = 120.0,
    ) -> tuple[int, str, str]:
        """Execute a docker CLI command asynchronously with timeout."""
        cmd = [self.docker_cmd, *args]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(cwd) if cwd else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds
            )
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            return proc.returncode or 0, stdout, stderr
        except TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            raise ContainerRuntimeError(
                f"Docker command '{args[0] if args else ''}' timed out after {timeout_seconds}s"
            )
        except FileNotFoundError:
            raise ContainerRuntimeError(
                f"Docker CLI executable '{self.docker_cmd}' not found on host system."
            )

    async def build_image(
        self,
        worktree_path: str | Path,
        tag: str,
        dockerfile: str = "Dockerfile",
    ) -> str:
        """Build preview container image from worktree and return authoritative sha256 digest."""
        worktree = Path(worktree_path)
        dockerfile_path = worktree / dockerfile

        if not dockerfile_path.exists():
            # If no explicit Dockerfile exists, look for common locations or create minimal fallback
            alt_dockerfiles = [worktree / "docker" / "Dockerfile", worktree / "Dockerfile.preview"]
            found = next((p for p in alt_dockerfiles if p.exists()), None)
            if found:
                dockerfile_path = found
            else:
                raise FileNotFoundError(
                    f"Dockerfile not found at '{dockerfile_path}' for preview build."
                )

        build_args = [
            "build",
            "-t",
            tag,
            "-f",
            str(dockerfile_path),
            str(worktree),
        ]
        returncode, stdout, stderr = await self._run_docker_cmd(
            build_args, cwd=worktree, timeout_seconds=300.0
        )
        if returncode != 0:
            sanitized_err = self._sanitize_text(stderr or stdout)
            raise ContainerRuntimeError(f"Docker image build failed: {sanitized_err}")

        # Retrieve authoritative image digest from docker inspect
        inspect_args = ["inspect", "--format={{.Id}}", tag]
        ret, insp_out, insp_err = await self._run_docker_cmd(inspect_args)
        if ret != 0 or not insp_out.strip():
            raise ContainerRuntimeError(
                f"Failed to inspect built image '{tag}': {self._sanitize_text(insp_err)}"
            )

        image_id = insp_out.strip()
        # Verify sha256 format
        if not image_id.startswith("sha256:"):
            image_id = f"sha256:{image_id}"
        return image_id

    async def start_preview_container(
        self,
        preview_session: PreviewSession,
        image_tag_or_digest: str,
        internal_port: int = 8787,
        env_vars: dict[str, str] | None = None,
    ) -> tuple[str, str, int]:
        """Start isolated preview container and return (container_id, preview_url, host_port)."""
        self._validate_db_safety(env_vars)

        host_port = preview_session.allocated_port or self.allocate_port()
        container_name = (
            preview_session.container_name
            or f"minime-preview-{preview_session.project_id}-{preview_session.change_name}-gen{preview_session.candidate_generation}"
        )
        # Sanitize container name for docker
        container_name = re.sub(r"[^a-zA-Z0-9_.-]", "-", container_name).lower()

        # Remove existing conflicting container if any
        await self.remove_container_by_name(container_name)

        run_args = [
            "run",
            "-d",
            "--name",
            container_name,
            "--label",
            "app=minime-preview",
            "--label",
            f"minime_preview_id={preview_session.preview_id}",
            "--label",
            f"minime_project={preview_session.project_id}",
            "--label",
            f"minime_change={preview_session.change_name}",
            "--label",
            f"minime_generation={preview_session.candidate_generation}",
            "-p",
            f"127.0.0.1:{host_port}:{internal_port}",
        ]

        if env_vars:
            for k, v in env_vars.items():
                run_args.extend(["-e", f"{k}={v}"])

        run_args.append(image_tag_or_digest)

        returncode, stdout, stderr = await self._run_docker_cmd(run_args)
        if returncode != 0:
            sanitized_err = self._sanitize_text(stderr or stdout)
            raise ContainerRuntimeError(
                f"Failed to start container '{container_name}': {sanitized_err}"
            )

        container_id = stdout.strip()
        preview_url = f"http://127.0.0.1:{host_port}"
        return container_id, preview_url, host_port

    async def probe_health(
        self,
        preview_url: str,
        health_path: str = "/api/v1/health",
        max_attempts: int = 30,
        interval_seconds: float = 0.5,
        timeout_seconds: float = 2.0,
    ) -> bool:
        """Actively probe preview endpoint until reachable HTTP 200/2xx or timeout."""
        target_urls = [
            f"{preview_url.rstrip('/')}{health_path}",
            f"{preview_url.rstrip('/')}/",
        ]

        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            for attempt in range(max_attempts):
                for url in target_urls:
                    try:
                        resp = await client.get(url)
                        if 200 <= resp.status_code < 400:
                            logger.info(
                                f"Preview health probe succeeded at '{url}' (attempt {attempt + 1})"
                            )
                            return True
                    except Exception as e:
                        logger.debug(f"Health probe attempt {attempt + 1} to '{url}' failed: {e}")
                await asyncio.sleep(interval_seconds)

        return False

    async def inspect_container(self, container_id_or_name: str) -> dict[str, Any]:
        """Inspect running container status."""
        returncode, stdout, stderr = await self._run_docker_cmd(["inspect", container_id_or_name])
        if returncode != 0:
            return {"exists": False, "running": False, "error": self._sanitize_text(stderr)}
        return {"exists": True, "running": True, "raw": stdout}

    async def stop_container(self, container_id_or_name: str) -> bool:
        """Stop container with bounded timeout."""
        returncode, _, _ = await self._run_docker_cmd(["stop", "-t", "5", container_id_or_name])
        return returncode == 0

    async def remove_container_by_name(self, container_name: str) -> bool:
        """Forcefully remove container by name if it exists."""
        returncode, _, _ = await self._run_docker_cmd(["rm", "-f", container_name])
        return returncode == 0

    async def teardown_preview(self, session: PreviewSession) -> bool:
        """Idempotently teardown and remove preview container resources."""
        target = session.container_id or session.container_name
        if target:
            await self.stop_container(target)
            await self.remove_container_by_name(target)

        session.status = PreviewStatus.TERMINATED
        session.terminated_at = utc_now()
        if self.uow:
            self.uow.preview_sessions.save(session)
            self.uow.events.save(
                Event(
                    project_id=session.project_id,
                    change_id=session.change_name,
                    event_type=EventType.PREVIEW_TERMINATED,
                    payload={"preview_id": session.preview_id, "change_name": session.change_name},
                )
            )
            self.uow.commit()
        return True

    async def reconcile_orphan_previews(self) -> list[str]:
        """Discover and prune only mini me-owned preview containers lacking active sessions."""
        cleaned_containers: list[str] = []
        returncode, stdout, stderr = await self._run_docker_cmd(
            [
                "ps",
                "-a",
                "--filter",
                "label=app=minime-preview",
                "--format",
                "{{.ID}}\t{{.Names}}\t{{.Labels}}",
            ]
        )
        if returncode != 0 or not stdout.strip():
            return cleaned_containers

        active_session_container_ids: set[str] = set()
        active_session_container_names: set[str] = set()
        if self.uow:
            active_sessions = self.uow.preview_sessions.list_active()
            for s in active_sessions:
                if s.container_id:
                    active_session_container_ids.add(s.container_id[:12])
                if s.container_name:
                    active_session_container_names.add(s.container_name)

        for line in stdout.strip().splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                cid = parts[0].strip()
                cname = parts[1].strip()
                labels = parts[2].strip() if len(parts) > 2 else ""

                # Safety check: ONLY touch containers bearing the app=minime-preview label
                if "app=minime-preview" not in labels:
                    continue

                is_active = (cid[:12] in active_session_container_ids) or (
                    cname in active_session_container_names
                )
                if not is_active:
                    logger.info(f"Reconciling orphan mini me preview container '{cname}' ({cid})")
                    await self.remove_container_by_name(cname)
                    cleaned_containers.append(cname)

        return cleaned_containers
