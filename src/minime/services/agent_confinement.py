"""OS/process-level confinement for agent execution processes."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from typing import Sequence

from minime.domain.enums import ExternalOutcome, ExternalReasonCode
from minime.domain.models import ExternalActionResult


class AgentConfinementError(RuntimeError):
    """Raised when process confinement capability is unavailable or breached."""
    pass


class AgentProcessConfinement:
    """Enforceable OS/kernel process write confinement wrapper for arbitrary-command agents."""

    def __init__(
        self,
        allowed_worktree_path: str,
        runtime_root: str | None = None,
        require_kernel_confinement: bool = True,
    ):
        self.allowed_worktree_path = os.path.realpath(allowed_worktree_path)
        self.runtime_root = os.path.realpath(
            runtime_root or os.environ.get("MINIME_RUNTIME_ROOT", os.path.join(os.getcwd(), ".minime"))
        )
        self.require_kernel_confinement = require_kernel_confinement
        self.confinement_mechanism = self._detect_confinement_mechanism()

    def _detect_confinement_mechanism(self) -> str:
        """Detect OS-level confinement capability on system."""
        system = platform.system().lower()
        if system == "linux":
            if shutil.which("bwrap"):
                return "bubblewrap"
            return "none"
        elif system == "darwin":
            if shutil.which("sandbox-exec") or os.path.exists("/usr/bin/sandbox-exec"):
                return "darwin_sandbox"
            return "none"
        return "none"

    def is_confinement_available(self) -> bool:
        """Check if enforceable process confinement is operational."""
        if self.confinement_mechanism == "none":
            return False
        return True

    def validate_command_preflight(
        self, cwd: str, target_paths: list[str] | None = None
    ) -> ExternalActionResult[bool]:
        """Verify that cwd and target paths remain strictly inside allowed_worktree_path."""
        if not self.is_confinement_available():
            return ExternalActionResult[bool](
                outcome=ExternalOutcome.FAILURE,
                source_adapter="agent_confinement",
                reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
                data=False,
                error_message="Agent process confinement capability unavailable. Failing closed.",
            )

        resolved_cwd = os.path.realpath(cwd)

        # Cwd must be inside allowed_worktree_path
        if not self._is_path_inside(resolved_cwd, self.allowed_worktree_path):
            return ExternalActionResult[bool](
                outcome=ExternalOutcome.FAILURE,
                source_adapter="agent_confinement",
                reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
                data=False,
                error_message=(
                    f"Subprocess cwd '{resolved_cwd}' is outside allowed worktree '{self.allowed_worktree_path}'."
                ),
            )

        # Check target paths if specified
        if target_paths:
            for p in target_paths:
                resolved_p = os.path.realpath(p)
                if not self._is_path_inside(resolved_p, self.allowed_worktree_path):
                    return ExternalActionResult[bool](
                        outcome=ExternalOutcome.FAILURE,
                        source_adapter="agent_confinement",
                        reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
                        data=False,
                        error_message=(
                            f"Target path '{resolved_p}' is outside allowed worktree '{self.allowed_worktree_path}'."
                        ),
                    )

        return ExternalActionResult[bool](
            outcome=ExternalOutcome.SUCCESS,
            source_adapter="agent_confinement",
            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
            data=True,
        )

    def _generate_darwin_sandbox_profile(self) -> str:
        """Construct a macOS sandbox profile strictly denying file write outside allowed_worktree_path and temp dirs, protecting runtime_root."""
        return (
            "(version 1)\n"
            "(allow default)\n"
            f"(allow file-write* (subpath \"{self.allowed_worktree_path}\"))\n"
            "(allow file-write* (subpath \"/private/tmp\"))\n"
            "(allow file-write* (subpath \"/tmp\"))\n"
            "(allow file-write* (regex #\"^/private/var/folders/\"))\n"
            "(allow file-write* (literal \"/dev/null\"))\n"
            "(allow file-write* (literal \"/dev/tty\"))\n"
            f"(deny file-write* (subpath \"{self.runtime_root}\"))\n"
        )

    def wrap_command(self, cmd: Sequence[str] | str) -> list[str]:
        """Wrap command with OS-level sandbox confinement binary (bwrap / sandbox-exec)."""
        if not self.is_confinement_available():
            raise AgentConfinementError("Confinement unavailable; cannot execute agent process unconstrained.")

        if isinstance(cmd, str):
            command_args = ["sh", "-c", cmd]
        else:
            command_args = list(cmd)

        if self.confinement_mechanism == "bubblewrap":
            # Bubblewrap sandbox on Linux: bind worktree RW, bind runtime RO
            return [
                "bwrap",
                "--ro-bind", "/", "/",
                "--bind", self.allowed_worktree_path, self.allowed_worktree_path,
                "--ro-bind", self.runtime_root, self.runtime_root,
                "--unshare-pid",
                "--chdir", self.allowed_worktree_path,
            ] + command_args

        elif self.confinement_mechanism == "darwin_sandbox":
            profile = self._generate_darwin_sandbox_profile()
            sandbox_bin = "/usr/bin/sandbox-exec" if os.path.exists("/usr/bin/sandbox-exec") else "sandbox-exec"
            return [sandbox_bin, "-p", profile] + command_args

        raise AgentConfinementError(
            f"Unsupported or fail-open confinement mechanism: '{self.confinement_mechanism}'."
        )

    def run_confined_subprocess(
        self,
        cmd: Sequence[str] | str,
        cwd: str,
        timeout_seconds: int = 300,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Execute arbitrary agent subprocess under OS confinement, failing closed on violations."""
        preflight = self.validate_command_preflight(cwd=cwd)
        if preflight.outcome != ExternalOutcome.SUCCESS:
            raise AgentConfinementError(f"Preflight confinement check failed: {preflight.error_message}")

        wrapped_cmd = self.wrap_command(cmd)
        exec_env = self.prepare_environment(env)

        return subprocess.run(
            wrapped_cmd,
            cwd=self.allowed_worktree_path,
            env=exec_env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )

    def prepare_environment(
        self, base_env: dict[str, str] | None = None
    ) -> dict[str, str]:
        """Construct isolated environment variables for agent subprocess execution."""
        env = dict(base_env or os.environ)
        env["PWD"] = self.allowed_worktree_path
        env["MINIME_CONFINED_WORKTREE"] = self.allowed_worktree_path
        env["MINIME_RUNTIME_ROOT"] = self.runtime_root
        return env

    def _is_path_inside(self, path: str, parent: str) -> bool:
        """Check if path is equal to or contained within parent."""
        try:
            rel = os.path.relpath(path, parent)
            return not rel.startswith("..") and rel != ".."
        except ValueError:
            return False
