"""OS/process-level confinement for agent execution processes."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import platform
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Sequence

from minime.domain.enums import ExternalOutcome, ExternalReasonCode
from minime.domain.models import ExternalActionResult

logger = logging.getLogger(__name__)


class AgentConfinementError(RuntimeError):
    """Raised when process confinement capability is unavailable or breached."""

    def __init__(self, message: str, *, environment_unavailable: bool = True):
        super().__init__(message)
        self.environment_unavailable = environment_unavailable


class AgentCredentialError(AgentConfinementError):
    """Raised when the existing Codex credential authority cannot be projected safely."""

    def __init__(self, message: str):
        super().__init__(message, environment_unavailable=False)


@dataclass(frozen=True)
class AgentProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    credential_rotation_detected: bool = False
    credential_access_refresh_only: bool = False
    stdout_capture_truncated: bool = False
    stderr_capture_truncated: bool = False


@dataclass
class AgentRuntimeState:
    """One private, disposable runtime view for a single confined subprocess."""

    host_root: Path
    sandbox_root: str
    environment: dict[str, str]
    auth_copy: Path | None = None
    initial_auth_digest: str | None = None
    antigravity_auth_copy: Path | None = None
    initial_antigravity_auth_digest: str | None = None
    initial_antigravity_auth_bytes: bytes | None = field(default=None, repr=False)
    credential_rotation_detected: bool = False
    credential_access_refresh_only: bool = False
    sensitive_values: tuple[str, ...] = field(default=(), repr=False)

    @staticmethod
    def _is_access_refresh_only(before: bytes, after: bytes) -> bool:
        """Accept only an access-token/expiry update; never a change of refresh authority."""
        try:
            previous = json.loads(before)
            updated = json.loads(after)
        except (ValueError, UnicodeDecodeError, TypeError):
            return False
        if not isinstance(previous, dict) or not isinstance(updated, dict):
            return False
        if previous.keys() != updated.keys() or "token" not in previous:
            return False
        if any(previous[key] != updated[key] for key in previous if key != "token"):
            return False

        old_token = previous["token"]
        new_token = updated["token"]
        if not isinstance(old_token, dict) or not isinstance(new_token, dict):
            return False
        if old_token.keys() != new_token.keys():
            return False
        required = {"access_token", "refresh_token", "expiry"}
        if not required.issubset(old_token):
            return False
        refresh = old_token["refresh_token"]
        access = new_token["access_token"]
        if not isinstance(refresh, str) or not refresh:
            return False
        if not isinstance(access, str) or not access:
            return False
        if refresh != new_token["refresh_token"]:
            return False
        if any(
            old_token[key] != new_token[key]
            for key in old_token
            if key not in {"access_token", "expiry"}
        ):
            return False
        return (
            old_token["access_token"] != new_token["access_token"]
            or old_token["expiry"] != new_token["expiry"]
        )

    def observe_credential_state(self) -> bool:
        """Classify any private auth rewrite without exposing secret values or digests."""
        self.credential_rotation_detected = False
        self.credential_access_refresh_only = False
        for path, expected in (
            (self.auth_copy, self.initial_auth_digest),
            (self.antigravity_auth_copy, self.initial_antigravity_auth_digest),
        ):
            if path is None or expected is None:
                continue
            try:
                current_bytes = path.read_bytes()
            except OSError:
                self.credential_rotation_detected = True
                return True
            if hashlib.sha256(current_bytes).hexdigest() != expected:
                self.credential_rotation_detected = True
                if (
                    path == self.antigravity_auth_copy
                    and self.initial_antigravity_auth_bytes is not None
                ):
                    self.credential_access_refresh_only = self._is_access_refresh_only(
                        self.initial_antigravity_auth_bytes, current_bytes
                    )
                return True
        return False


def is_authorized_cache_shape(
    path: str | Path, expected_uid: int, job_id: str | None = None
) -> bool:
    """Validate that the path strictly conforms to an authorized minime bytecode cache shape.

    Authorized shapes:
    1. Primary under ~/.cache (or XDG_CACHE_HOME):
       Must be strictly <user_cache_root>/minime/pycache/<job_id>.
    2. Ephemeral under /tmp or gettempdir():
       Parent must be strictly one of the allowed temp roots, and filename must be
       minime_cache_{expected_uid}_{job_id}.
    """
    raw_path = Path(path)
    temp_roots = [
        Path(tempfile.gettempdir()),
        Path(tempfile.gettempdir()).resolve(),
        Path("/tmp"),
        Path("/tmp").resolve(),
    ]
    user_cache_roots = [
        Path.home() / ".cache",
        (Path.home() / ".cache").resolve(),
    ]
    if os.environ.get("XDG_CACHE_HOME"):
        user_cache_roots.append(Path(os.environ["XDG_CACHE_HOME"]).expanduser())
        user_cache_roots.append(Path(os.environ["XDG_CACHE_HOME"]).expanduser().resolve())

    # Primary check: strictly <user_cache_root>/minime/pycache/<job_id>
    for uc_root in user_cache_roots:
        for p in (raw_path, raw_path.resolve()):
            try:
                rel = p.relative_to(uc_root)
                if len(rel.parts) == 3 and rel.parts[0] == "minime" and rel.parts[1] == "pycache":
                    leaf = rel.parts[2]
                    if job_id is None:
                        if leaf:
                            return True
                    elif leaf == job_id:
                        return True
            except ValueError:
                pass

    # Ephemeral check: strictly <temp_root>/minime_cache_{expected_uid}_{job_id}
    for tr in temp_roots:
        for p in (raw_path, raw_path.resolve()):
            if p.parent == tr:
                name = p.name
                prefix = f"minime_cache_{expected_uid}_"
                if name.startswith(prefix):
                    leaf = name[len(prefix) :]
                    if job_id is None:
                        if leaf:
                            return True
                    elif leaf == job_id or leaf.endswith(f"_{job_id}"):
                        return True

    return False


def validate_secure_cache_path(
    path: str | Path,
    expected_uid: int | None = None,
    job_id: str | None = None,
) -> Path:
    """Strictly validate a private bytecode cache path and all its ancestor components.

    Enforces:
    - Path matches authoritative dedicated bytecode cache shape (not arbitrary home/temp dir).
    - Every original component from filesystem root down is inspected without following symlinks.
    - Path exists, is a directory, and is NOT a symlink.
    - Owner strictly matches expected_uid (defaults to current process UID).
    - Permissions are strictly 0700 (no group or others permissions).
    - Inode identity matches between un-followed and resolved path.
    - Path is located inside an authorized base root (user cache or system temp directory).
    - Path is not an allowed root itself.
    """
    target_uid = os.getuid() if expected_uid is None else expected_uid
    raw_path = Path(path)

    # 1. Authoritative shape check
    if not is_authorized_cache_shape(raw_path, expected_uid=target_uid, job_id=job_id):
        raise PermissionError(
            f"Path '{raw_path}' is not an authorized dedicated minime bytecode cache path shape."
        )

    temp_roots = [
        Path(tempfile.gettempdir()),
        Path(tempfile.gettempdir()).resolve(),
        Path("/tmp"),
        Path("/tmp").resolve(),
    ]
    home_root = Path.home().resolve()

    # 2. Inspect all UNRESOLVED original ancestor components using anchored parent descriptors (dir_fd)
    root_dir = raw_path.parts[0] if raw_path.is_absolute() else str(Path.cwd())
    current_walk = Path(root_dir)
    root_open_flags = os.O_RDONLY | (os.O_DIRECTORY if hasattr(os, "O_DIRECTORY") else 0)
    open_dir_flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_DIRECTORY"):
        open_dir_flags |= os.O_DIRECTORY
    current_fd = os.open(root_dir, root_open_flags)

    try:
        for part in raw_path.parts[1:]:
            current_walk = current_walk / part
            try:
                st = os.stat(part, dir_fd=current_fd, follow_symlinks=False)
            except FileNotFoundError:
                break
            except OSError as e:
                raise PermissionError(
                    f"Failed to stat cache path component '{current_walk}': {e}"
                ) from e

            if stat.S_ISLNK(st.st_mode):
                if (
                    platform.system().lower() == "darwin"
                    and current_walk in (Path("/var"), Path("/tmp"))
                    and os.readlink(current_walk)
                    in ("private/var", "private/tmp", "/private/var", "/private/tmp")
                ):
                    resolved_root = current_walk.resolve()
                    next_fd = os.open(str(resolved_root), open_dir_flags)
                    os.close(current_fd)
                    current_fd = next_fd
                    continue
                raise PermissionError(
                    f"Secure cache path component cannot be a symlink: '{current_walk}'"
                )

            try:
                next_fd = os.open(part, open_dir_flags, dir_fd=current_fd)
            except OSError as exc:
                raise PermissionError(
                    f"Failed to open cache path component '{current_walk}' with O_NOFOLLOW: {exc}"
                ) from exc
            st = os.fstat(next_fd)
            os.close(current_fd)
            current_fd = next_fd

            try:
                resolved_walk = current_walk.resolve()
            except OSError:
                resolved_walk = current_walk

            mode = stat.S_IMODE(st.st_mode)
            if (mode & 0o002 != 0) and not (st.st_mode & stat.S_ISVTX):
                raise PermissionError(
                    f"World-writable ancestor directory '{current_walk}' lacks sticky bit (+t)."
                )

            if home_root in resolved_walk.parents or resolved_walk == home_root:
                if st.st_uid != target_uid:
                    raise PermissionError(
                        f"Secure cache ancestor '{current_walk}' owned by UID {st.st_uid}, expected {target_uid}."
                    )
                if mode & 0o022 != 0:
                    raise PermissionError(
                        f"Secure cache ancestor '{current_walk}' has insecure permissions (group or world writable)."
                    )
    finally:
        os.close(current_fd)

    if not raw_path.exists() or not raw_path.is_dir():
        raise PermissionError(f"Secure cache path does not exist or is not a directory: {raw_path}")

    st_leaf = os.lstat(raw_path)
    if stat.S_ISLNK(st_leaf.st_mode):
        raise PermissionError(f"Secure cache path cannot be a symlink: {raw_path}")
    if st_leaf.st_uid != target_uid:
        raise PermissionError(
            f"Secure cache path '{raw_path}' owned by UID {st_leaf.st_uid}, expected {target_uid}."
        )
    if stat.S_IMODE(st_leaf.st_mode) & 0o077 != 0:
        raise PermissionError(
            f"Secure cache path '{raw_path}' mode must be strictly 0700, got {oct(stat.S_IMODE(st_leaf.st_mode))}."
        )

    p = raw_path.resolve()
    st_resolved = os.stat(p)
    if st_resolved.st_dev != st_leaf.st_dev or st_resolved.st_ino != st_leaf.st_ino:
        raise PermissionError(f"Secure cache path resolved to a different inode: {p}")

    allowed_roots = [home_root] + temp_roots
    if p in allowed_roots:
        raise PermissionError(f"Cache path cannot be a root directory: {p}")

    is_under_allowed = False
    for root in allowed_roots:
        if root in p.parents:
            is_under_allowed = True
            break
    if not is_under_allowed:
        raise PermissionError(
            f"Refusing to mount cache path outside authorized roots (~/.cache or /tmp): {p}"
        )

    authorized_home_caches = [(Path.home() / ".cache").resolve()]
    if os.environ.get("XDG_CACHE_HOME"):
        authorized_home_caches.append(Path(os.environ["XDG_CACHE_HOME"]).expanduser().resolve())

    if home_root in p.parents:
        if not any(auth_c in p.parents or p == auth_c for auth_c in authorized_home_caches):
            raise PermissionError(
                f"Primary cache path under home must be located inside authorized cache directory (~/.cache or $XDG_CACHE_HOME): {p}"
            )

    return p


def safe_prepare_cache_dir(
    target_path: Path | str,
    expected_uid: int,
    job_id: str | None = None,
) -> Path:
    """Safely validate ancestors and create missing directory components using anchored parent descriptors.

    Threat model and guarantees:
    - Path must match an authorized cache shape (<user_cache_root>/minime/pycache/<job_id> or ephemeral).
    - Traversals use anchored parent directory file descriptors (`dir_fd`) with `O_NOFOLLOW` and `O_DIRECTORY`.
      Each component is created or opened relative to its verified parent descriptor, eliminating intermediate
      path component replacement races (TOCTOU) by foreign processes or unprivileged users.
    - Any world-writable ancestor directory is verified to have the sticky bit (+t) set.
    - If the target directory already exists: must be owned by expected_uid and mode 0700. If not, fail-closed
      without modifying or repairing foreign/unsafe directories.
    - Missing components are created component-by-component with mode 0700 via dir_fd and verified via fstat.
    - Residual concurrency threat is strictly bounded to same-UID local attacker executing concurrent renames on
      their own directory hierarchy, which cannot elevate privileges.
    """
    raw_path = Path(target_path)
    target_uid = expected_uid

    if not is_authorized_cache_shape(raw_path, expected_uid=target_uid, job_id=job_id):
        raise PermissionError(
            f"Path '{raw_path}' is not an authorized dedicated minime bytecode cache path shape."
        )

    home_root = Path.home().resolve()
    open_dir_flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_DIRECTORY"):
        open_dir_flags |= os.O_DIRECTORY

    root_dir = raw_path.parts[0] if raw_path.is_absolute() else str(Path.cwd())
    current_walk = Path(root_dir)
    root_open_flags = os.O_RDONLY | (os.O_DIRECTORY if hasattr(os, "O_DIRECTORY") else 0)
    current_fd = os.open(root_dir, root_open_flags)

    try:
        for part in raw_path.parts[1:]:
            current_walk = current_walk / part
            try:
                st = os.stat(part, dir_fd=current_fd, follow_symlinks=False)
                exists = True
            except FileNotFoundError:
                exists = False
            except OSError as e:
                raise PermissionError(
                    f"Failed to stat cache component '{part}' in '{current_walk}': {e}"
                ) from e

            if exists:
                if stat.S_ISLNK(st.st_mode):
                    if (
                        platform.system().lower() == "darwin"
                        and current_walk in (Path("/var"), Path("/tmp"))
                        and os.readlink(current_walk)
                        in ("private/var", "private/tmp", "/private/var", "/private/tmp")
                    ):
                        resolved_root = current_walk.resolve()
                        next_fd = os.open(str(resolved_root), open_dir_flags)
                        os.close(current_fd)
                        current_fd = next_fd
                        continue
                    raise PermissionError(
                        f"Secure cache path component cannot be a symlink: '{current_walk}'"
                    )
                if not stat.S_ISDIR(st.st_mode):
                    raise PermissionError(
                        f"Secure cache path component is not a directory: '{current_walk}'"
                    )

                try:
                    next_fd = os.open(part, open_dir_flags, dir_fd=current_fd)
                except OSError as exc:
                    raise PermissionError(
                        f"Failed to open cache component '{current_walk}' with O_NOFOLLOW: {exc}"
                    ) from exc
                st = os.fstat(next_fd)
                os.close(current_fd)
                current_fd = next_fd

                try:
                    resolved_walk = current_walk.resolve()
                except OSError:
                    resolved_walk = current_walk

                mode = stat.S_IMODE(st.st_mode)
                if (mode & 0o002 != 0) and not (st.st_mode & stat.S_ISVTX):
                    raise PermissionError(
                        f"World-writable ancestor directory '{current_walk}' lacks sticky bit (+t)."
                    )

                if home_root in resolved_walk.parents or resolved_walk == home_root:
                    if st.st_uid != target_uid:
                        raise PermissionError(
                            f"Secure cache ancestor '{current_walk}' owned by UID {st.st_uid}, expected {target_uid}."
                        )
                    if mode & 0o022 != 0:
                        raise PermissionError(
                            f"Secure cache ancestor '{current_walk}' has insecure permissions."
                        )

                if current_walk == raw_path:
                    # Existing target directory: must already have mode 0700 and correct owner.
                    # DO NOT chmod or repair an existing unsafe target. Fail closed!
                    if st.st_uid != target_uid:
                        raise PermissionError(
                            f"Existing cache directory '{current_walk}' owned by UID {st.st_uid}, expected {target_uid}."
                        )
                    if mode & 0o077 != 0:
                        raise PermissionError(
                            f"Existing cache directory '{current_walk}' mode must be strictly 0700, got {oct(mode)}."
                        )
            else:
                # Component does not exist: create with mode 0700 via dir_fd
                try:
                    os.mkdir(part, mode=0o700, dir_fd=current_fd)
                except OSError as exc:
                    raise PermissionError(
                        f"Failed to create secure cache directory '{current_walk}': {exc}"
                    ) from exc

                try:
                    next_fd = os.open(part, open_dir_flags, dir_fd=current_fd)
                except OSError as exc:
                    raise PermissionError(
                        f"Failed to open created cache directory '{current_walk}' with O_NOFOLLOW: {exc}"
                    ) from exc
                try:
                    os.fchmod(next_fd, 0o700)
                    st = os.fstat(next_fd)
                finally:
                    os.close(current_fd)
                    current_fd = next_fd

                if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
                    raise PermissionError(
                        f"Created cache component is not a directory: '{current_walk}'"
                    )
                if st.st_uid != target_uid:
                    raise PermissionError(
                        f"Created cache component owned by wrong UID: {st.st_uid}"
                    )
    finally:
        os.close(current_fd)

    return validate_secure_cache_path(raw_path, expected_uid=target_uid, job_id=job_id)


class AgentProcessConfinement:
    """Enforce OS-level write confinement with attempt-private non-code state."""

    SANDBOX_RUNTIME_ROOT = "/run/minime-agent"

    @staticmethod
    def _set_parent_death_signal() -> None:
        """Make the Linux confinement wrapper die with its worker parent."""
        if platform.system().lower() != "linux":
            return
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
            os._exit(127)

    def __init__(
        self,
        allowed_worktree_path: str,
        runtime_root: str | None = None,
        require_kernel_confinement: bool = True,
        private_state_parent: str | None = None,
    ):
        self.allowed_worktree_path = self._canonical_directory(
            allowed_worktree_path, "assigned worktree"
        )
        default_root = self.resolve_runtime_root()
        self.runtime_root = self._canonical_directory(
            runtime_root or default_root,
            "runtime root",
        )
        if self._is_path_inside(
            self.allowed_worktree_path, self.runtime_root
        ) or self._is_path_inside(self.runtime_root, self.allowed_worktree_path):
            raise AgentConfinementError(
                "Assigned worktree and runtime root must be separate canonical directories."
            )
        self.private_state_parent = private_state_parent
        self.require_kernel_confinement = require_kernel_confinement
        self.confinement_mechanism = self._detect_confinement_mechanism()

    @staticmethod
    def resolve_runtime_root() -> str:
        """Resolve the configured host runtime root without creating it.

        The service deployment provides this path through ``MINIME_RUNTIME_ROOT``
        or one of the known managed installation roots.  A missing fallback is
        intentionally returned as-is so preflight fails closed; test fixtures
        must provide their own private directory explicitly.
        """
        configured = os.environ.get("MINIME_RUNTIME_ROOT")
        if configured:
            return configured
        cwd_minime = os.path.join(os.getcwd(), ".minime")
        if os.path.isdir(cwd_minime):
            return cwd_minime
        if os.path.isdir("/opt/minime/runtime"):
            return "/opt/minime/runtime"
        if os.path.isdir("/opt/minime/app/.minime"):
            return "/opt/minime/app/.minime"
        return cwd_minime

    @staticmethod
    def _canonical_directory(raw_path: str, label: str) -> str:
        path = Path(raw_path).expanduser()
        try:
            resolved = path.resolve(strict=False)
            info = resolved.stat() if resolved.exists() else None
        except OSError as exc:
            raise AgentConfinementError(f"{label} is unavailable.") from exc
        if info is not None and not stat.S_ISDIR(info.st_mode):
            raise AgentConfinementError(f"{label} is not a directory.")
        return str(resolved)

    @staticmethod
    def _validate_temp_parent(raw_path: str) -> Path:
        raw = Path(raw_path)
        try:
            parent = raw.resolve(strict=True)
            info = parent.stat()
        except OSError as exc:
            raise AgentConfinementError("Private runtime temporary parent is unavailable.") from exc
        if not stat.S_ISDIR(info.st_mode):
            raise AgentConfinementError("Private runtime temporary parent is not a directory.")
        mode = stat.S_IMODE(info.st_mode)
        if mode & stat.S_IWOTH and not mode & stat.S_ISVTX:
            raise AgentConfinementError(
                "Private runtime temporary parent is world-writable without sticky-bit protection."
            )
        return parent

    @staticmethod
    def _detect_confinement_mechanism() -> str:
        """Detect OS-level confinement capability on system."""
        system = platform.system().lower()
        if system == "linux":
            if shutil.which("bwrap"):
                return "bubblewrap"
            return "none"
        if system == "darwin":
            if shutil.which("sandbox-exec") or os.path.exists("/usr/bin/sandbox-exec"):
                return "darwin_sandbox"
        return "none"

    def is_confinement_available(self) -> bool:
        """Check if enforceable process confinement is operational."""
        return self.confinement_mechanism != "none"

    @classmethod
    def is_host_confinement_available(cls) -> bool:
        """Report platform capability without constructing a worktree sandbox."""
        return cls._detect_confinement_mechanism() != "none"

    def validate_command_preflight(
        self, cwd: str, target_paths: list[str] | None = None
    ) -> ExternalActionResult[bool]:
        """Verify cwd and targets remain strictly inside the assigned worktree."""
        if not self.is_confinement_available():
            return ExternalActionResult[bool](
                outcome=ExternalOutcome.FAILURE,
                source_adapter="agent_confinement",
                reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
                data=False,
                error_message="Agent process confinement capability unavailable. Failing closed.",
            )
        if not Path(self.allowed_worktree_path).is_dir():
            return ExternalActionResult[bool](
                outcome=ExternalOutcome.FAILURE,
                source_adapter="agent_confinement",
                reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
                data=False,
                error_message="Assigned worktree is not an available directory.",
            )
        if not Path(self.runtime_root).is_dir():
            return ExternalActionResult[bool](
                outcome=ExternalOutcome.FAILURE,
                source_adapter="agent_confinement",
                reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
                data=False,
                error_message="Runtime root is not an available directory.",
            )

        paths = [cwd, *(target_paths or [])]
        for raw_path in paths:
            resolved = os.path.realpath(raw_path)
            if not self._is_path_inside(resolved, self.allowed_worktree_path):
                return ExternalActionResult[bool](
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="agent_confinement",
                    reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
                    data=False,
                    error_message=(
                        f"Subprocess path '{resolved}' is outside assigned worktree "
                        f"'{self.allowed_worktree_path}'."
                    ),
                )
        return ExternalActionResult[bool](
            outcome=ExternalOutcome.SUCCESS,
            source_adapter="agent_confinement",
            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
            data=True,
        )

    @staticmethod
    def is_local_environment_preflight_error(message: str | None) -> bool:
        """Identify only local confinement/runtime availability failures."""
        normalized = (message or "").lower()
        return any(
            marker in normalized
            for marker in (
                "confinement capability unavailable",
                "assigned worktree is not an available directory",
                "runtime root is not an available directory",
                "private runtime temporary parent is unavailable",
                "private runtime temporary parent is not a directory",
            )
        )

    @contextmanager
    def runtime_session(
        self,
        base_env: dict[str, str] | None = None,
        codex_auth_source: str | None = None,
        antigravity_auth_source: str | None = None,
        *,
        extra_env: dict[str, str] | None = None,
    ) -> Iterator[AgentRuntimeState]:
        """Create one private runtime with only explicitly authorized provider credentials."""
        temp_parent = self._validate_temp_parent(
            self.private_state_parent or self._default_private_state_parent()
        )
        with tempfile.TemporaryDirectory(
            prefix="minime-agent-state-", dir=str(temp_parent)
        ) as raw_root:
            host_root = Path(raw_root).resolve()
            os.chmod(host_root, 0o700)
            subdirs = {
                name: host_root / name
                for name in ("home", "codex", "tmp", "cache", "state", "config", "runtime")
            }
            for directory in subdirs.values():
                directory.mkdir(mode=0o700)
                os.chmod(directory, 0o700)
            (subdirs["codex"] / "tmp").mkdir(mode=0o700)

            safe_env = self.prepare_environment(base_env)
            sandbox_root = self.SANDBOX_RUNTIME_ROOT
            sandbox_dirs = {name: f"{sandbox_root}/{name}" for name in subdirs}
            if self.confinement_mechanism != "bubblewrap":
                sandbox_dirs = {name: str(path) for name, path in subdirs.items()}
            safe_env.update(
                {
                    "HOME": sandbox_dirs["home"],
                    "TMPDIR": sandbox_dirs["tmp"],
                    "TMP": sandbox_dirs["tmp"],
                    "TEMP": sandbox_dirs["tmp"],
                    "XDG_CONFIG_HOME": sandbox_dirs["config"],
                    "XDG_CACHE_HOME": sandbox_dirs["cache"],
                    "XDG_STATE_HOME": sandbox_dirs["state"],
                    "XDG_RUNTIME_DIR": sandbox_dirs["runtime"],
                    "PWD": self.allowed_worktree_path,
                    "MINIME_CONFINED_WORKTREE": self.allowed_worktree_path,
                    "MINIME_RUNTIME_ROOT": self.runtime_root,
                }
            )

            if extra_env:
                for k, v in extra_env.items():
                    safe_env[k] = v

            auth_copy: Path | None = None
            initial_auth_digest: str | None = None
            antigravity_auth_copy: Path | None = None
            initial_antigravity_auth_digest: str | None = None
            initial_antigravity_auth_bytes: bytes | None = None
            sensitive_values: tuple[str, ...] = ()
            if extra_env:
                for v in extra_env.values():
                    if len(v) >= 8:
                        sensitive_values = tuple(sorted(set(sensitive_values) | {v}, key=len, reverse=True))
            if codex_auth_source is not None:
                auth_copy = subdirs["codex"] / "auth.json"
                self._copy_codex_auth(codex_auth_source, auth_copy)
                initial_auth_digest = hashlib.sha256(auth_copy.read_bytes()).hexdigest()
                sensitive_values = self._read_credential_values(auth_copy)
                safe_env["CODEX_HOME"] = sandbox_dirs["codex"]
            else:
                safe_env.pop("CODEX_HOME", None)

            if platform.system().lower() == "darwin":
                host_library = (
                    Path(base_env.get("HOME", "")).expanduser()
                    if base_env and base_env.get("HOME")
                    else Path.home()
                ) / "Library"
                if not host_library.exists():
                    host_library = Path.home() / "Library"
                sandbox_library = subdirs["home"] / "Library"
                if host_library.exists() and not sandbox_library.exists():
                    try:
                        sandbox_library.symlink_to(host_library)
                    except OSError:
                        pass

            if antigravity_auth_source is not None:
                source_p = Path(antigravity_auth_source)
                gemini_home = subdirs["home"] / ".gemini"
                gemini_home.mkdir(mode=0o700, exist_ok=True)
                os.chmod(gemini_home, 0o700)
                antigravity_cli_dir = gemini_home / "antigravity-cli"
                antigravity_cli_dir.mkdir(mode=0o700, exist_ok=True)
                os.chmod(antigravity_cli_dir, 0o700)
                antigravity_auth_copy = antigravity_cli_dir / "antigravity-oauth-token"
                self._copy_authorized_auth_file(antigravity_auth_source, antigravity_auth_copy)
                if source_p.name == "jetski-standalone-oauth-token":
                    jetski_copy = gemini_home / "jetski-standalone-oauth-token"
                    jetski_copy.write_bytes(antigravity_auth_copy.read_bytes())
                    os.chmod(jetski_copy, 0o600)
                initial_antigravity_auth_bytes = antigravity_auth_copy.read_bytes()
                initial_antigravity_auth_digest = hashlib.sha256(
                    initial_antigravity_auth_bytes
                ).hexdigest()
                sensitive_values = tuple(
                    sorted(
                        set(sensitive_values)
                        | set(self._read_opaque_credential_values(antigravity_auth_copy)),
                        key=len,
                        reverse=True,
                    )
                )

            runtime = AgentRuntimeState(
                host_root=host_root,
                sandbox_root=sandbox_root,
                environment=safe_env,
                auth_copy=auth_copy,
                initial_auth_digest=initial_auth_digest,
                antigravity_auth_copy=antigravity_auth_copy,
                initial_antigravity_auth_digest=initial_antigravity_auth_digest,
                initial_antigravity_auth_bytes=initial_antigravity_auth_bytes,
                sensitive_values=sensitive_values,
            )
            try:
                yield runtime
            finally:
                runtime.observe_credential_state()

    @staticmethod
    def _read_credential_values(auth_path: Path) -> tuple[str, ...]:
        """Read credential string values in memory for output scrubbing only."""
        try:
            payload = json.loads(auth_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AgentCredentialError("Authorized Codex auth file is not valid JSON.") from exc
        values: set[str] = set()

        def collect(value: object) -> None:
            if isinstance(value, str) and len(value) >= 8:
                values.add(value)
            elif isinstance(value, dict):
                for child in value.values():
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)

        collect(payload)
        return tuple(sorted(values, key=len, reverse=True))

    @staticmethod
    def _read_opaque_credential_values(auth_path: Path) -> tuple[str, ...]:
        """Return redaction candidates for a single opaque Antigravity token file."""
        try:
            value = auth_path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as exc:
            raise AgentCredentialError(
                "Authorized Antigravity credentials are unreadable."
            ) from exc
        if not value:
            return ()
        candidates = {value} if len(value) >= 8 else set()
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            payload = None

        def collect_strings(item: object) -> None:
            if isinstance(item, str) and len(item) >= 8:
                candidates.add(item)
            elif isinstance(item, dict):
                for child in item.values():
                    collect_strings(child)
            elif isinstance(item, list):
                for child in item:
                    collect_strings(child)

        collect_strings(payload)
        return tuple(sorted(candidates, key=len, reverse=True))

    @staticmethod
    def _scrub_credential_values(output: bytes, values: tuple[str, ...]) -> bytes:
        for value in values:
            output = output.replace(value.encode("utf-8"), b"[REDACTED_CODEX_CREDENTIAL]")
        return output

    @staticmethod
    def _default_private_state_parent() -> str:
        if platform.system().lower() == "linux" and Path("/var/tmp").is_dir():
            return "/var/tmp"
        return tempfile.gettempdir()

    @staticmethod
    def _copy_codex_auth(source: str, target: Path) -> None:
        AgentProcessConfinement._copy_authorized_auth_file(source, target)

    @staticmethod
    def _copy_authorized_auth_file(source: str, target: Path) -> None:
        source_path = Path(source).expanduser()
        try:
            if source_path.resolve(strict=True) != source_path.absolute():
                raise AgentCredentialError(
                    "Authorized provider auth path contains a symlink component."
                )
            source_info = source_path.lstat()
            if not stat.S_ISREG(source_info.st_mode) or stat.S_ISLNK(source_info.st_mode):
                raise AgentCredentialError("Authorized provider auth source is not a regular file.")
            groups = set(os.getgroups()) | {os.getegid()}
            if source_info.st_uid != os.geteuid() and source_info.st_gid not in groups:
                raise AgentCredentialError(
                    "Authorized provider auth source is not readable by this service identity."
                )
            if stat.S_IMODE(source_info.st_mode) & 0o077:
                raise AgentCredentialError(
                    "Authorized provider auth source has unsafe group/world permissions."
                )
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            source_fd = os.open(source_path, flags)
            try:
                opened_info = os.fstat(source_fd)
                if (
                    not stat.S_ISREG(opened_info.st_mode)
                    or opened_info.st_ino != source_info.st_ino
                    or opened_info.st_dev != source_info.st_dev
                    or opened_info.st_uid != source_info.st_uid
                    or opened_info.st_gid != source_info.st_gid
                ):
                    raise AgentCredentialError(
                        "Authorized provider auth source changed during validation."
                    )
                target_fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                try:
                    while chunk := os.read(source_fd, 65536):
                        view = memoryview(chunk)
                        while view:
                            written = os.write(target_fd, view)
                            view = view[written:]
                    after_copy = os.fstat(source_fd)
                    if (
                        after_copy.st_size != opened_info.st_size
                        or after_copy.st_mtime_ns != opened_info.st_mtime_ns
                        or after_copy.st_ctime_ns != opened_info.st_ctime_ns
                    ):
                        raise AgentCredentialError(
                            "Authorized provider auth source changed while being copied."
                        )
                    os.fsync(target_fd)
                    os.fchmod(target_fd, 0o600)
                finally:
                    os.close(target_fd)
            finally:
                os.close(source_fd)
        except AgentCredentialError:
            raise
        except OSError as exc:
            raise AgentCredentialError("Authorized provider credentials are unavailable.") from exc

    @staticmethod
    def codex_auth_source(base_env: dict[str, str] | None = None) -> str:
        env = base_env or os.environ
        codex_home = env.get("CODEX_HOME")
        home = env.get("HOME")
        if codex_home:
            root = Path(codex_home).expanduser()
        elif home:
            root = Path(home).expanduser() / ".codex"
        else:
            root = Path.home() / ".codex"
        return str(root / "auth.json")

    @staticmethod
    def antigravity_auth_source(base_env: dict[str, str] | None = None) -> str:
        """Resolve the one standalone Antigravity CLI auth file; never its whole home."""
        env = base_env or os.environ
        home = env.get("HOME")
        root = Path(home).expanduser() if home else Path.home()
        standard = root / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
        jetski = root / ".gemini" / "jetski-standalone-oauth-token"
        if not standard.is_file() and jetski.is_file():
            return str(jetski)
        return str(standard)

    @staticmethod
    def _build_darwin_sandbox_profile(
        allowed_worktree_path: str,
        runtime_root: str,
        private_state_root: str | None = None,
    ) -> str:
        """Deny host writes except the assigned worktree and private session state."""
        private_allows: list[str] = []
        if private_state_root:
            private_allows.append(f'(allow file-write* (subpath "{private_state_root}"))\n')
            resolved_private = str(Path(private_state_root).resolve())
            if resolved_private != private_state_root:
                private_allows.append(f'(allow file-write* (subpath "{resolved_private}"))\n')
        private_allow = "".join(private_allows)

        worktree_allows: list[str] = [f'(allow file-write* (subpath "{allowed_worktree_path}"))\n']
        resolved_worktree = str(Path(allowed_worktree_path).resolve())
        if resolved_worktree != allowed_worktree_path:
            worktree_allows.append(f'(allow file-write* (subpath "{resolved_worktree}"))\n')
        worktree_allow = "".join(worktree_allows)

        runtime_denies: list[str] = [f'(deny file-write* (subpath "{runtime_root}"))\n']
        resolved_runtime = str(Path(runtime_root).resolve())
        if resolved_runtime != runtime_root:
            runtime_denies.append(f'(deny file-write* (subpath "{resolved_runtime}"))\n')
        runtime_deny = "".join(runtime_denies)

        return (
            "(version 1)\n"
            "(allow default)\n"
            "(deny file-write*)\n"
            + worktree_allow
            + private_allow
            + '(allow file-write* (literal "/dev/null"))\n'
            + '(allow file-write* (literal "/dev/zero"))\n'
            + '(allow file-write* (literal "/dev/tty"))\n'
            + '(allow file-write* (literal "/dev/ptmx"))\n'
            + '(allow file-write* (regex #"^/dev/tty[0-9a-zA-Z]"))\n'
            + '(allow file-write* (regex #"^/dev/pty[0-9a-zA-Z]"))\n'
            + "(allow pseudo-tty)\n"
            + '(allow file-write* (regex #"^/dev/fd/"))\n'
            + '(allow file-write* (regex #"^/dev/std(in|out|err)"))\n'
            + runtime_deny
        )

    def _generate_profile(self, private_state_root: str | None = None) -> str:
        return self._build_darwin_sandbox_profile(
            self.allowed_worktree_path, self.runtime_root, private_state_root
        )

    def _generate_darwin_sandbox_profile(self) -> str:
        return self._generate_profile()

    @staticmethod
    def _host_resolver_projection(
        resolv_conf_path: str = "/etc/resolv.conf", run_root: str = "/run"
    ) -> tuple[str, str] | None:
        """Return the exact resolver file hidden by Bubblewrap's private /run."""
        try:
            resolver_link = Path(resolv_conf_path)
            if not resolver_link.is_absolute():
                raise OSError("resolver path is not absolute")
            link_info = resolver_link.lstat()
            raw_link_target = (
                os.readlink(resolver_link) if stat.S_ISLNK(link_info.st_mode) else None
            )
            lexical_target = (
                Path(os.path.normpath(str(resolver_link.parent / raw_link_target)))
                if raw_link_target is not None and not Path(raw_link_target).is_absolute()
                else Path(os.path.normpath(raw_link_target))
                if raw_link_target is not None
                else resolver_link
            )
            target = resolver_link.resolve(strict=True)
            target_info = target.stat()
            run_path = Path(run_root).resolve(strict=True)
            after_link_info = resolver_link.lstat()
            if (
                after_link_info.st_ino != link_info.st_ino
                or after_link_info.st_dev != link_info.st_dev
                or after_link_info.st_mode != link_info.st_mode
                or after_link_info.st_mtime_ns != link_info.st_mtime_ns
                or after_link_info.st_ctime_ns != link_info.st_ctime_ns
                or (
                    raw_link_target is not None
                    and (
                        not stat.S_ISLNK(after_link_info.st_mode)
                        or os.readlink(resolver_link) != raw_link_target
                    )
                )
            ):
                raise OSError("resolver link changed during validation")
        except OSError as exc:
            raise AgentConfinementError(
                "Host DNS resolver configuration is unavailable or unverifiable."
            ) from exc

        if not stat.S_ISREG(target_info.st_mode) or not os.access(target, os.R_OK):
            raise AgentConfinementError(
                "Host DNS resolver configuration is not a readable regular file."
            )

        def is_beneath(path: Path, root: Path) -> bool:
            try:
                return os.path.commonpath((str(path), str(root))) == str(root)
            except ValueError:
                return False

        if is_beneath(lexical_target, run_path):
            destination = lexical_target
        elif is_beneath(target, run_path):
            destination = target
        else:
            return None
        if destination == run_path:
            raise AgentConfinementError(
                "Host DNS resolver target conflicts with the private agent runtime."
            )
        if is_beneath(destination, Path(AgentProcessConfinement.SANDBOX_RUNTIME_ROOT)):
            raise AgentConfinementError(
                "Host DNS resolver target conflicts with the private agent runtime."
            )
        return str(target), str(destination)

    @staticmethod
    def _bubblewrap_resolver_mounts(source: str, destination: str) -> list[str]:
        """Create only missing parents below the private /run, then bind one file RO."""
        source_path = Path(source)
        destination_path = Path(destination)
        run_root = Path("/run")
        if (
            not source_path.is_absolute()
            or not destination_path.is_absolute()
            or str(destination_path) != os.path.normpath(destination)
            or destination_path == run_root
            or run_root not in destination_path.parents
            or destination_path == Path(AgentProcessConfinement.SANDBOX_RUNTIME_ROOT)
            or Path(AgentProcessConfinement.SANDBOX_RUNTIME_ROOT) in destination_path.parents
        ):
            raise AgentConfinementError("Host DNS resolver projection path is unsafe.")

        parents: list[Path] = []
        parent = destination_path.parent
        while parent != run_root:
            if run_root not in parent.parents:
                raise AgentConfinementError("Host DNS resolver projection escaped private /run.")
            parents.append(parent)
            parent = parent.parent

        mounts: list[str] = []
        for directory in reversed(parents):
            mounts.extend(("--dir", str(directory)))
        mounts.extend(("--ro-bind", str(source_path), str(destination_path)))
        return mounts

    def wrap_command(
        self,
        cmd: Sequence[str] | str,
        runtime_state: AgentRuntimeState | None = None,
        *,
        read_only_worktree: bool = False,
        unshare_network: bool = False,
        secure_cache_path: str | Path | None = None,
        job_id: str | None = None,
    ) -> list[str]:
        """Wrap a process and bind only its assigned worktree plus private state."""
        if not self.is_confinement_available():
            raise AgentConfinementError(
                "Confinement unavailable; cannot execute agent process unconstrained."
            )
        command_args = ["sh", "-c", cmd] if isinstance(cmd, str) else list(cmd)

        validated_cache: Path | None = None
        if secure_cache_path is not None:
            try:
                validated_cache = validate_secure_cache_path(
                    secure_cache_path, expected_uid=os.getuid(), job_id=job_id
                )
            except (PermissionError, ValueError, OSError) as err:
                raise AgentConfinementError(
                    f"Secure cache path rejected by confinement: {err}",
                    environment_unavailable=True,
                ) from err

        if self.confinement_mechanism == "bubblewrap":
            worktree_mount = "--ro-bind" if read_only_worktree else "--bind"
            wrapped = [
                "bwrap",
                "--ro-bind",
                "/",
                "/",
                "--dev",
                "/dev",
                worktree_mount,
                self.allowed_worktree_path,
                self.allowed_worktree_path,
                "--ro-bind",
                self.runtime_root,
                self.runtime_root,
            ]
            if validated_cache is not None:
                cache_str = str(validated_cache)
                wrapped.extend(["--dir", cache_str, "--bind", cache_str, cache_str])
            if runtime_state is not None:
                wrapped.extend(
                    [
                        "--tmpfs",
                        "/run",
                    ]
                )
                resolver_projection = self._host_resolver_projection()
                if resolver_projection is not None:
                    wrapped.extend(self._bubblewrap_resolver_mounts(*resolver_projection))
                wrapped.extend(
                    [
                        "--dir",
                        runtime_state.sandbox_root,
                        "--bind",
                        str(runtime_state.host_root),
                        runtime_state.sandbox_root,
                    ]
                )
            if unshare_network:
                wrapped.append("--unshare-net")
            wrapped.extend(
                [
                    "--die-with-parent",
                    "--unshare-pid",
                    "--chdir",
                    self.allowed_worktree_path,
                    *command_args,
                ]
            )
            return wrapped

        if self.confinement_mechanism == "darwin_sandbox":
            profile = self._generate_profile(
                str(runtime_state.host_root) if runtime_state is not None else None
            )
            sandbox_bin = (
                "/usr/bin/sandbox-exec"
                if os.path.exists("/usr/bin/sandbox-exec")
                else "sandbox-exec"
            )
            return [sandbox_bin, "-p", profile, *command_args]

        raise AgentConfinementError(
            f"Unsupported or fail-open confinement mechanism: '{self.confinement_mechanism}'."
        )

    async def run_confined_async_subprocess(
        self,
        cmd: Sequence[str] | str,
        cwd: str,
        *,
        input_bytes: bytes | None,
        timeout_seconds: float | None = None,
        env: dict[str, str] | None = None,
        codex_auth_source: str | None = None,
        antigravity_auth_source: str | None = None,
        unshare_network: bool = False,
        read_only_worktree: bool = False,
        extra_env: dict[str, str] | None = None,
    ) -> AgentProcessResult:
        """Run an async subprocess, guaranteeing process and private-state cleanup."""
        preflight = self.validate_command_preflight(cwd=cwd)
        if preflight.outcome != ExternalOutcome.SUCCESS:
            raise AgentConfinementError(preflight.error_message or "Confinement preflight failed.")
        runtime_state = None
        try:
            with self.runtime_session(
                env, codex_auth_source, antigravity_auth_source, extra_env=extra_env
            ) as runtime_state:
                command = self.wrap_command(
                    cmd,
                    runtime_state,
                    unshare_network=unshare_network,
                    read_only_worktree=read_only_worktree,
                )
                process = await asyncio.create_subprocess_exec(
                    *command,
                    cwd=self.allowed_worktree_path,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=runtime_state.environment,
                    start_new_session=True,
                    preexec_fn=(
                        self._set_parent_death_signal
                        if self.confinement_mechanism == "bubblewrap"
                        else None
                    ),
                )
                from minime.services.progress_watchdog import (
                    ProgressWatchdog,
                    WatchdogSignal,
                    WatchdogState,
                )

                watchdog = ProgressWatchdog(
                    worktree_path=self.allowed_worktree_path,
                )
                timed_out = False
                stdout_chunks: list[bytes] = []
                stderr_chunks: list[bytes] = []

                async def _read_stream(
                    stream: asyncio.StreamReader | None, chunks: list[bytes], sig: WatchdogSignal
                ) -> bool:
                    """Drain the pipe while bounding retained bytes, including unbroken NDJSON lines.

                    Reading fixed-size chunks avoids StreamReader.readline's 64 KiB line
                    limit. Exceeding the capture budget is observable; it never
                    silently turns a partial stdout stream into a final answer.
                    """
                    if not stream:
                        return False
                    max_capture_bytes = 8 * 1024 * 1024
                    captured = 0
                    truncated = False
                    while True:
                        chunk = await stream.read(64 * 1024)
                        if not chunk:
                            break
                        remaining = max_capture_bytes - captured
                        if remaining > 0:
                            retained = chunk[:remaining]
                            chunks.append(retained)
                            captured += len(retained)
                        if len(chunk) > remaining:
                            truncated = True
                        watchdog.record_activity(sig)
                    return truncated

                if process.stdin:
                    if input_bytes:
                        process.stdin.write(input_bytes)
                        await process.stdin.drain()
                    process.stdin.close()

                stdout_task = asyncio.create_task(
                    _read_stream(process.stdout, stdout_chunks, WatchdogSignal.STDOUT_EMISSION)
                )
                stderr_task = asyncio.create_task(
                    _read_stream(process.stderr, stderr_chunks, WatchdogSignal.STDERR_EMISSION)
                )

                start_time = time.monotonic()
                try:
                    while True:
                        if process.returncode is not None:
                            break
                        try:
                            await asyncio.wait_for(
                                process.wait(), timeout=watchdog.check_interval_seconds
                            )
                            break
                        except asyncio.TimeoutError:
                            state = watchdog.evaluate_tick(process.pid)
                            if state == WatchdogState.STALLED:
                                timed_out = True
                                logger.warning(
                                    f"Process PID {process.pid} confirmed stalled ({watchdog.diagnostic_reason or 'inactivity'}). Terminating process group."
                                )
                                await self._terminate_process_group(process)
                                break

                            # A caller may still provide a bounded timeout for a
                            # genuinely bounded technical operation. Agent
                            # workflows pass None: elapsed wall-clock time is
                            # never a workflow termination authority.
                            elapsed = time.monotonic() - start_time
                            if timeout_seconds is not None and elapsed >= float(timeout_seconds):
                                timed_out = True
                                logger.warning(
                                    f"Process PID {process.pid} exceeded authorized confinement security timeout "
                                    f"({elapsed:.1f}s >= {timeout_seconds}s). Terminating process group."
                                )
                                await self._terminate_process_group(process)
                                break

                            if (
                                state == WatchdogState.SUSPECTED_STALL
                                and watchdog.diagnostic_reason
                            ):
                                logger.debug(
                                    f"Process PID {process.pid} inactive ({watchdog.diagnostic_reason}); preserving process under uncertainty."
                                )
                    capture_results = await asyncio.gather(
                        stdout_task, stderr_task, return_exceptions=True
                    )
                    stdout_capture_truncated = capture_results[0] is not False
                    stderr_capture_truncated = capture_results[1] is not False
                    stdout = b"".join(stdout_chunks)
                    stderr = b"".join(stderr_chunks)
                except BaseException:
                    task = asyncio.current_task()
                    was_cancelled = task is not None and task.cancelling() > 0
                    if was_cancelled:
                        task.uncancel()
                    stdout_task.cancel()
                    stderr_task.cancel()
                    try:
                        await self._terminate_process_group(process)
                    finally:
                        if was_cancelled:
                            task.cancel()
                    raise
                rotation = runtime_state.observe_credential_state()
                access_refresh_only = rotation and runtime_state.credential_access_refresh_only
                if access_refresh_only:
                    # Include newly issued access credentials in redaction; they stay
                    # private to this attempt and are never copied back to the host.
                    try:
                        new_values = self._read_opaque_credential_values(
                            runtime_state.antigravity_auth_copy
                        )
                        runtime_state.sensitive_values = tuple(
                            sorted(
                                set(runtime_state.sensitive_values) | set(new_values),
                                key=len,
                                reverse=True,
                            )
                        )
                    except AgentCredentialError:
                        access_refresh_only = False
                if rotation and not access_refresh_only:
                    # Unknown changes or refresh-token rotation must fail closed;
                    # new secrets might be present in child output.
                    stdout = b""
                    stderr = b"Provider credential rotation was not persisted."
                return AgentProcessResult(
                    returncode=process.returncode if process.returncode is not None else -1,
                    stdout=self._scrub_credential_values(stdout, runtime_state.sensitive_values),
                    stderr=self._scrub_credential_values(stderr, runtime_state.sensitive_values),
                    timed_out=timed_out,
                    credential_rotation_detected=rotation,
                    credential_access_refresh_only=access_refresh_only,
                    stdout_capture_truncated=stdout_capture_truncated,
                    stderr_capture_truncated=stderr_capture_truncated,
                )
        except asyncio.CancelledError:
            raise
        except AgentConfinementError:
            raise
        except (OSError, subprocess.SubprocessError) as exc:
            raise AgentConfinementError(
                "Confined process runtime could not be initialized."
            ) from exc

    async def _terminate_process_group(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except OSError:
            pass
        try:
            # Stream readers are already active in the caller. Waiting for the
            # process avoids competing ``communicate()`` readers that can force
            # a graceful SIGTERM handler to be killed before it flushes.
            await asyncio.wait_for(process.wait(), timeout=5.0)
            return
        except Exception:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            await process.wait()
        except Exception:
            pass

    def run_confined_subprocess(
        self,
        cmd: Sequence[str] | str,
        cwd: str,
        timeout_seconds: int = 300,
        env: dict[str, str] | None = None,
        *,
        codex_auth_source: str | None = None,
        antigravity_auth_source: str | None = None,
        unshare_network: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        """Synchronous confined execution used by checks with no Codex credentials."""
        preflight = self.validate_command_preflight(cwd=cwd)
        if preflight.outcome != ExternalOutcome.SUCCESS:
            raise AgentConfinementError(
                f"Preflight confinement check failed: {preflight.error_message}"
            )
        with self.runtime_session(env, codex_auth_source, antigravity_auth_source) as runtime_state:
            wrapped = self.wrap_command(cmd, runtime_state, unshare_network=unshare_network)
            process: subprocess.Popen[str] | None = None
            try:
                process = subprocess.Popen(
                    wrapped,
                    cwd=self.allowed_worktree_path,
                    env=runtime_state.environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    start_new_session=True,
                )
                try:
                    stdout, stderr = process.communicate(timeout=timeout_seconds)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except OSError:
                        pass
                    try:
                        stdout, stderr = process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except OSError:
                            pass
                        stdout, stderr = process.communicate()
                    raise
                result = subprocess.CompletedProcess(wrapped, process.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                raise
            except (OSError, subprocess.SubprocessError) as exc:
                raise AgentConfinementError(
                    "Confined process runtime could not be initialized."
                ) from exc
            runtime_state.observe_credential_state()
            return result

    def prepare_environment(self, base_env: dict[str, str] | None = None) -> dict[str, str]:
        """Return a sanitized inherited environment before per-attempt paths are set."""
        source = os.environ if base_env is None else base_env
        env: dict[str, str] = {}
        secret_markers = (
            "API_KEY",
            "TOKEN",
            "PASSWORD",
            "SECRET",
            "PRIVATE_KEY",
            "DATABASE_URL",
            "CONNECTION_STRING",
        )
        for key, value in source.items():
            normalized = key.upper()
            if normalized.startswith("MINIME_") or any(
                marker in normalized for marker in secret_markers
            ):
                continue
            env[key] = value
        return env

    @staticmethod
    def _is_path_inside(path: str, parent: str) -> bool:
        """Use path-component containment, never textual-prefix containment."""
        try:
            Path(path).relative_to(Path(parent))
            return True
        except ValueError:
            return False
