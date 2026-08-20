"""Sequential deterministic checks runner."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from minime.domain.models import CheckResult
from minime.logging import redact_secrets


@dataclass(frozen=True)
class ChecksRunResult:
    passed: bool
    results: list[CheckResult]


class ChecksRunner:
    def __init__(self, output_limit: int = 4000):
        self.output_limit = output_limit

    async def run(self, job_id: str, checks: list[dict], worktree_path: str | Path) -> ChecksRunResult:
        results: list[CheckResult] = []
        for index, check in enumerate(checks, start=1):
            name = str(check.get("name") or f"check-{index}")
            command = str(check.get("command") or "")
            if not command:
                result = CheckResult(
                    job_id=job_id,
                    check_name=name,
                    command=command,
                    exit_code=2,
                    duration_ms=0,
                    output_snippet="Missing check command.",
                )
                results.append(result)
                return ChecksRunResult(passed=False, results=results)
            start = asyncio.get_running_loop().time()
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=str(worktree_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            duration_ms = int((asyncio.get_running_loop().time() - start) * 1000)
            output = (stdout + stderr).decode(errors="replace")
            snippet = redact_secrets(output)[-self.output_limit:]
            result = CheckResult(
                job_id=job_id,
                check_name=name,
                command=command,
                exit_code=proc.returncode or 0,
                duration_ms=duration_ms,
                output_snippet=snippet,
            )
            results.append(result)
            if result.exit_code != 0:
                return ChecksRunResult(passed=False, results=results)
        return ChecksRunResult(passed=True, results=results)
