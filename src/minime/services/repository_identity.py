"""Canonical, host-sensitive repository identity normalization."""

from __future__ import annotations

from urllib.parse import urlparse


def normalize_repository_identity(repo_input: str) -> str:
    """Return the canonical identity for a repository transport or durable identity.

    GitHub.com is the only host whose durable canonical identity omits the
    transport host (``owner/repo``). Other remote hosts retain their host in
    the identity so they cannot be confused with GitHub or local shorthand.
    Local paths and ``file://`` sources are intentionally left unchanged.
    """
    cleaned = repo_input.strip()
    if not cleaned:
        return ""
    if cleaned.startswith("file://") or cleaned.startswith("/"):
        return cleaned

    host: str | None = None
    repository_path: str | None = None
    if cleaned.startswith("git@") and ":" in cleaned:
        host, repository_path = cleaned[4:].split(":", 1)
    elif cleaned.startswith(("http://", "https://", "ssh://")):
        parsed = urlparse(cleaned)
        host = parsed.hostname
        repository_path = parsed.path.lstrip("/")

    if host is not None and repository_path is not None:
        path = repository_path.rstrip("/")
        if path.endswith(".git"):
            path = path[:-4]
        if not path or "/" not in path:
            return cleaned
        normalized_host = host.lower()
        if normalized_host == "github.com":
            return path.lower()
        return f"{normalized_host}/{path.lower()}"

    legacy_github_prefix = "github.com/"
    if cleaned.lower().startswith(legacy_github_prefix):
        path = cleaned[len(legacy_github_prefix) :].rstrip("/")
        if path.endswith(".git"):
            path = path[:-4]
        if path and "/" in path:
            return path.lower()

    if cleaned.count("/") == 1 and not cleaned.startswith(("./", "../")):
        return cleaned.lower()
    return cleaned
