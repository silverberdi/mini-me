"""Protected host-side storage for project-owned GitHub App credentials."""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
from pathlib import Path


class ProjectCredentialStore:
    """Store private key material outside PostgreSQL, Git, API responses and logs."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or os.environ.get("MINIME_PROJECT_SECRET_ROOT", "/var/lib/minime/secrets/projects"))

    def store_github_app(
        self, project_id: str, app_id: str, installation_id: str, private_key: str
    ) -> str:
        if not all(value.strip() for value in (project_id, app_id, installation_id, private_key)):
            raise ValueError("GitHub App credentials are incomplete")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", project_id):
            raise ValueError("Project id is not a safe credential-store identifier")
        if "BEGIN PRIVATE KEY" not in private_key and "BEGIN RSA PRIVATE KEY" not in private_key:
            raise ValueError("GitHub App private key must be a PEM private key")

        root = self.root
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        root_stat = root.lstat()
        if not stat.S_ISDIR(root_stat.st_mode) or stat.S_IMODE(root_stat.st_mode) & 0o077:
            raise PermissionError("Project credential root must be a private, non-symlink directory")

        project_dir = root / project_id
        project_dir.mkdir(mode=0o700, exist_ok=True)
        project_stat = project_dir.lstat()
        if not stat.S_ISDIR(project_stat.st_mode) or stat.S_IMODE(project_stat.st_mode) & 0o077:
            raise PermissionError("Project credential directory is not private")

        reference = secrets.token_urlsafe(24)
        path = project_dir / f"{reference}.json"
        payload = json.dumps(
            {
                "app_id": app_id.strip(),
                "installation_id": installation_id.strip(),
                "private_key": private_key,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return reference

    def remove_github_app(self, project_id: str, reference: str) -> None:
        """Remove only the exact opaque credential written during a failed transaction."""
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", project_id):
            return
        if not re.fullmatch(r"[A-Za-z0-9_-]{20,64}", reference):
            return
        path = self.root / project_id / f"{reference}.json"
        if path.is_file() and not path.is_symlink():
            path.unlink()

    def load_github_app(self, project_id: str, reference: str) -> dict[str, str]:
        """Read one project-scoped credential after checking identity and filesystem mode."""
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", project_id):
            raise ValueError("Invalid project credential identity")
        if not re.fullmatch(r"[A-Za-z0-9_-]{20,64}", reference):
            raise ValueError("Invalid project credential reference")
        project_dir = self.root / project_id
        path = project_dir / f"{reference}.json"
        try:
            root_stat = self.root.lstat()
            directory_stat = project_dir.lstat()
            file_stat = path.lstat()
            if (
                not stat.S_ISDIR(root_stat.st_mode)
                or stat.S_IMODE(root_stat.st_mode) & 0o077
                or
                not stat.S_ISDIR(directory_stat.st_mode)
                or stat.S_IMODE(directory_stat.st_mode) & 0o077
                or not stat.S_ISREG(file_stat.st_mode)
                or stat.S_IMODE(file_stat.st_mode) & 0o077
            ):
                raise ValueError("Project credential storage permissions are unsafe")
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise ValueError("Project credential reference is unavailable") from None
        if not all(isinstance(payload.get(field), str) and payload[field] for field in ("app_id", "installation_id", "private_key")):
            raise ValueError("Project credential entry is malformed")
        return payload
