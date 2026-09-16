# Deterministic CLI invocation preflight against the installed CLI version.

from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from minime.config import CliInvocationProfile

_SEARCH_PATH = (
    f"{Path.home()}/.local/bin:/opt/homebrew/bin:/usr/local/bin:{os.environ.get("PATH", "")}"
)


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    reason: str | None = None
    checked_flags: tuple[str, ...] = field(default_factory=tuple)
    missing_flags: tuple[str, ...] = field(default_factory=tuple)


def _flag_tokens(args: tuple[str, ...]) -> list[str]:
    tokens: list[str] = []
    for arg in args:
        if not arg.startswith("-") or arg == "-":
            continue
        tokens.append(arg.split("=")[0])
    return tokens


def _subcommand(args: tuple[str, ...]) -> str | None:
    for arg in args:
        if not arg.startswith("-"):
            return arg
    return None


async def preflight_cli_invocation(
    profile: CliInvocationProfile,
    help_runner=None,
    timeout: float = 10.0,
) -> PreflightResult:
    resolved = shutil.which(profile.executable, path=_SEARCH_PATH)
    if not resolved:
        return PreflightResult(ok=False, reason="EXECUTABLE_MISSING")

    flags = _flag_tokens(profile.args)
    subcommand = _subcommand(profile.args)
    if subcommand:
        help_cmd = [resolved, subcommand, "--help"]
    else:
        help_cmd = [resolved, "--help"]

    if help_runner is None:

        async def _run():
            proc = await asyncio.create_subprocess_exec(
                *help_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            try:
                out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                try:
                    proc.terminate()
                except OSError:
                    pass
                return -1, ""
            combined = (out.decode(errors="replace") + err.decode(errors="replace")).lower()
            return proc.returncode, combined

        help_runner = _run

    exit_code, help_text = await help_runner()
    if exit_code != 0:
        return PreflightResult(
            ok=False, reason="UNSUPPORTED_SUBCOMMAND", checked_flags=tuple(flags)
        )

    missing = [f for f in flags if f.lower() not in help_text]
    if missing:
        return PreflightResult(
            ok=False,
            reason="UNSUPPORTED_FLAG",
            checked_flags=tuple(flags),
            missing_flags=tuple(missing),
        )
    return PreflightResult(ok=True, checked_flags=tuple(flags))
