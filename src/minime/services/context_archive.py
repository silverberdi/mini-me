"""Bounded, non-executing ZIP intake for project context packages."""

from __future__ import annotations

import hashlib
import io
import os
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True)
class ExtractedContextPackage:
    sha256: str
    files: tuple[str, ...]
    total_bytes: int


class UnsafeContextArchive(ValueError):
    """The package violates the bounded context archive policy."""


class ContextArchiveExtractor:
    """Validate a ZIP completely before writing regular files to a private workspace."""

    max_archive_bytes = 64 * 1024 * 1024
    max_entries = 2_000
    max_uncompressed_bytes = 256 * 1024 * 1024
    max_file_bytes = 32 * 1024 * 1024
    max_path_depth = 20
    rejected_suffixes = {
        ".app",
        ".bat",
        ".bz2",
        ".cmd",
        ".com",
        ".dll",
        ".dylib",
        ".exe",
        ".gz",
        ".jar",
        ".msi",
        ".rar",
        ".sh",
        ".tar",
        ".tgz",
        ".xz",
        ".7z",
        ".zip",
        ".ps1",
    }

    def extract(self, archive: bytes, destination: str | Path) -> ExtractedContextPackage:
        if not archive or len(archive) > self.max_archive_bytes:
            raise UnsafeContextArchive("Context archive is empty or exceeds the compressed-size limit")
        requested_root = Path(destination).absolute()
        if requested_root.is_symlink():
            raise UnsafeContextArchive("Context extraction root must not be a symlink")
        requested_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            root_stat = requested_root.lstat()
        except OSError:
            raise UnsafeContextArchive("Context extraction root could not be inspected") from None
        if (
            not stat.S_ISDIR(root_stat.st_mode)
            or stat.S_IMODE(root_stat.st_mode) & 0o077
            or root_stat.st_uid != os.geteuid()
        ):
            raise UnsafeContextArchive("Context extraction root must be owned and private to the service")
        root = requested_root.resolve()
        if not root.is_dir():
            raise UnsafeContextArchive("Context extraction root is not a safe directory")
        if any(root.iterdir()):
            raise UnsafeContextArchive("Context extraction requires a new empty workspace")

        try:
            zf = zipfile.ZipFile(io.BytesIO(archive))
        except (zipfile.BadZipFile, OSError):
            raise UnsafeContextArchive("Context package is not a valid ZIP archive") from None

        entries: list[tuple[zipfile.ZipInfo, str]] = []
        seen: set[str] = set()
        files: set[str] = set()
        total = 0
        with zf:
            members = zf.infolist()
            if not members or len(members) > self.max_entries:
                raise UnsafeContextArchive("Context archive entry count is outside permitted limits")
            for info in members:
                raw_name = info.filename
                if "\\" in raw_name or "\x00" in raw_name:
                    raise UnsafeContextArchive("Context archive contains an invalid path")
                path = PurePosixPath(raw_name)
                if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
                    raise UnsafeContextArchive("Context archive contains an absolute or traversal path")
                if len(path.parts) > self.max_path_depth:
                    raise UnsafeContextArchive("Context archive path nesting exceeds the limit")
                normalized = path.as_posix().rstrip("/")
                folded = normalized.casefold()
                if folded in seen:
                    raise UnsafeContextArchive("Context archive contains duplicate or colliding paths")
                seen.add(folded)

                unix_mode = info.external_attr >> 16
                file_type = stat.S_IFMT(unix_mode)
                is_directory = info.is_dir()
                if file_type == stat.S_IFLNK or (file_type not in (0, stat.S_IFREG, stat.S_IFDIR)):
                    raise UnsafeContextArchive("Context archive links and special files are forbidden")
                if is_directory:
                    entries.append((info, normalized))
                    continue
                if file_type == stat.S_IFDIR or (unix_mode & 0o111):
                    raise UnsafeContextArchive("Context archive executable files are forbidden")
                if _is_secret_path(normalized):
                    raise UnsafeContextArchive("Context archive contains a secret-bearing file path")
                if Path(normalized).suffix.lower() in self.rejected_suffixes:
                    raise UnsafeContextArchive(
                        "Context archive contains a disallowed executable or nested archive file"
                    )
                if info.file_size > self.max_file_bytes:
                    raise UnsafeContextArchive("Context archive contains an oversized file")
                total += info.file_size
                if total > self.max_uncompressed_bytes:
                    raise UnsafeContextArchive("Context archive expands beyond the size limit")
                if info.compress_size == 0 and info.file_size > 0:
                    raise UnsafeContextArchive("Context archive has an invalid compression ratio")
                if info.compress_size and info.file_size / info.compress_size > 200:
                    raise UnsafeContextArchive("Context archive compression ratio exceeds the limit")
                entries.append((info, normalized))
                files.add(folded)

            for _info, relative in entries:
                parts = PurePosixPath(relative).parts
                if any("/".join(parts[:index]).casefold() in files for index in range(1, len(parts))):
                    raise UnsafeContextArchive("Context archive contains a file/directory path collision")

            validated_payloads: dict[str, bytes] = {}
            for info, relative in entries:
                if info.is_dir():
                    continue
                try:
                    payload = zf.read(info)
                except (RuntimeError, OSError, zipfile.BadZipFile):
                    raise UnsafeContextArchive("Context archive could not be read safely") from None
                if len(payload) != info.file_size:
                    raise UnsafeContextArchive("Context archive entry size did not match its manifest")
                if _contains_secret_marker(payload):
                    raise UnsafeContextArchive("Context archive appears to contain secret material")
                validated_payloads[relative] = payload

            extracted: list[str] = []
            for info, relative in entries:
                target = root.joinpath(*PurePosixPath(relative).parts)
                if not target.resolve().is_relative_to(root):
                    raise UnsafeContextArchive("Context archive path escapes the extraction root")
                if info.is_dir():
                    target.mkdir(mode=0o700, parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                if target.exists() or target.is_symlink():
                    raise UnsafeContextArchive("Context extraction refuses to overwrite existing files")
                with target.open("xb") as stream:
                    stream.write(validated_payloads[relative])
                target.chmod(0o600)
                extracted.append(relative)

        return ExtractedContextPackage(
            sha256=hashlib.sha256(archive).hexdigest(),
            files=tuple(sorted(extracted)),
            total_bytes=total,
        )


def _contains_secret_marker(payload: bytes) -> bool:
    lowered = payload.lower()
    return any(
        marker in lowered
        for marker in (
            b"-----begin private key-----",
            b"-----begin rsa private key-----",
            b"ghp_",
            b"github_pat_",
            b"akia",
            b"aws_secret_access_key",
        )
    )


def _is_secret_path(relative_path: str) -> bool:
    """Reject common credential filenames before their contents reach an agent or Git."""
    path = PurePosixPath(relative_path)
    name = path.name.casefold()
    return (
        name == ".env"
        or name.startswith(".env.")
        or name in {"id_rsa", "id_ed25519", "credentials", "secrets.json"}
        or path.suffix.casefold() in {".der", ".key", ".p12", ".pfx", ".pem"}
        or ".ssh" in {part.casefold() for part in path.parts}
        or ".aws" in {part.casefold() for part in path.parts}
    )
