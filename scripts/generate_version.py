#!/usr/bin/env python3
"""Generate version.json with the metadata of the artifact being deployed.

Consumed by the frontend (login + shell) and by the backend /health endpoint so
both surfaces report the exact same deployed version, commit SHA, and build time.

Resolution order for the version:
  1. $VERSION / $GIT_TAG environment (set by GitHub Actions from the tag, e.g. v0.2.3)
  2. `git describe --tags --exact-match` when the build runs on a tag
  3. package.json "version" as a fallback
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def resolve_version() -> str:
    raw = os.environ.get("VERSION") or os.environ.get("GIT_TAG")
    if raw:
        return raw.lstrip("v")
    try:
        tagged = git("describe", "--tags", "--exact-match")
        return tagged.lstrip("v")
    except subprocess.CalledProcessError:
        pass
    repo_root = Path(__file__).resolve().parents[1]
    pkg = json.loads((repo_root / "package.json").read_text(encoding="utf-8"))
    return str(pkg.get("version", "0.0.0"))


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    try:
        commit_sha = git("-C", str(repo_root), "rev-parse", "HEAD")
    except subprocess.CalledProcessError:
        commit_sha = "unknown"

    data = {
        "version": resolve_version(),
        "commit_sha": commit_sha,
        "build_date": datetime.now(timezone.utc).isoformat(),
    }

    targets = sys.argv[1:] or [
        str(repo_root / "frontend" / "public" / "version.json"),
        str(repo_root / "src" / "minime" / "static" / "version.json"),
    ]
    for target in targets:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path}: {json.dumps(data)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
