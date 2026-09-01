"""Sequential deterministic checks runner."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from minime.domain.enums import EvidenceDiagnosticStatus
from minime.domain.models import CheckResult, EvidenceDiagnostic
from minime.logging import redact_secrets


@dataclass(frozen=True)
class ChecksRunResult:
    passed: bool
    results: list[CheckResult]
    diagnostics: list[EvidenceDiagnostic] = field(default_factory=list)


class ChecksRunner:
    def __init__(self, output_limit: int = 4000):
        self.output_limit = output_limit

    async def run(
        self,
        job_id: str,
        checks: list[dict],
        worktree_path: str | Path,
        candidate_sha: str = "",
        candidate_generation: int | None = None,
        attempt_id: str | None = None,
    ) -> ChecksRunResult:
        results: list[CheckResult] = []
        diagnostics: list[EvidenceDiagnostic] = []
        env_identity = str(worktree_path)

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
                    candidate_sha=candidate_sha,
                    candidate_generation=candidate_generation,
                )
                results.append(result)
                diag = EvidenceDiagnostic(
                    job_id=job_id,
                    attempt_id=attempt_id,
                    stage_type="CHECKS",
                    check_name=name,
                    diagnostic_status=EvidenceDiagnosticStatus.FAIL,
                    environment_identity=env_identity,
                    candidate_sha=candidate_sha,
                    reason="Missing check command.",
                    evidence_reference={"exit_code": 2},
                )
                diagnostics.append(diag)
                continue

            env = os.environ.copy()
            inherited_database_url = env.pop("MINIME_DATABASE_URL", None)
            env.pop("MINIME_EXPECTED_DATABASE", None)

            wt_path = Path(worktree_path)
            wt_venv_bin = wt_path / ".venv" / "bin"
            repo_venv_bin = Path.cwd() / ".venv" / "bin"
            standard_paths = [
                str(wt_venv_bin),
                str(repo_venv_bin),
                "/Users/silveriobernal/.local/bin",
                "/opt/homebrew/bin",
                "/usr/local/bin",
                "/usr/bin",
                "/bin",
            ]
            current_path = env.get("PATH", "")
            env["PATH"] = (
                ":".join(p for p in standard_paths if p not in current_path) + ":" + current_path
            )
            current_pythonpath = env.get("PYTHONPATH", "")
            pythonpath_dirs = [
                str(wt_path),
                str(wt_path / "src"),
                str(Path.cwd()),
                str(Path.cwd() / "src"),
            ]
            env["PYTHONPATH"] = ":".join(
                p for p in pythonpath_dirs if p not in current_pythonpath
            ) + (":" + current_pythonpath if current_pythonpath else "")
            if "VIRTUAL_ENV" not in env:
                if wt_venv_bin.parent.exists():
                    env["VIRTUAL_ENV"] = str(wt_venv_bin.parent)
                elif repo_venv_bin.parent.exists():
                    env["VIRTUAL_ENV"] = str(repo_venv_bin.parent)
            if check.get("disposable_postgres") is True:
                expected = str(
                    check.get("expected_database") or check.get("expected_db") or ""
                ).strip()
                database_url = str(
                    check.get("database_url") or inherited_database_url or ""
                ).strip()
                actual = (
                    (urlparse(database_url).path or "").lstrip("/").split("/", 1)[0]
                    if database_url
                    else ""
                )
                if (
                    not expected
                    or not database_url
                    or not database_url.startswith(("postgresql://", "postgresql+"))
                    or actual.lower() == "minime"
                    or actual != expected
                ):
                    reason = "Disposable PostgreSQL check rejected: expected_database must be non-empty and database URL must target a non-canonical database with the exact expected name."
                    result = CheckResult(
                        job_id=job_id,
                        check_name=name,
                        command=command,
                        exit_code=126,
                        duration_ms=0,
                        output_snippet=reason,
                        candidate_sha=candidate_sha,
                        candidate_generation=candidate_generation,
                    )
                    results.append(result)
                    diagnostics.append(
                        EvidenceDiagnostic(
                            job_id=job_id,
                            attempt_id=attempt_id,
                            stage_type="CHECKS",
                            check_name=name,
                            diagnostic_status=EvidenceDiagnosticStatus.FAIL,
                            environment_identity=env_identity,
                            candidate_sha=candidate_sha,
                            reason=reason,
                            evidence_reference={"exit_code": 126},
                        )
                    )
                    continue
                env["MINIME_DATABASE_URL"] = database_url
                env["MINIME_EXPECTED_DATABASE"] = expected

            cmd_to_run = command
            if "pytest" in command and "-o pythonpath" not in command:
                cmd_to_run = f'{command} -o pythonpath=". src"'

            start = asyncio.get_running_loop().time()
            try:
                proc = await asyncio.create_subprocess_shell(
                    cmd_to_run,
                    cwd=str(worktree_path),
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await proc.communicate()
                duration_ms = int((asyncio.get_running_loop().time() - start) * 1000)
                output = (stdout + stderr).decode(errors="replace")
                exit_code = proc.returncode or 0
            except Exception as err:
                duration_ms = int((asyncio.get_running_loop().time() - start) * 1000)
                output = f"Environment execution failure: {err}"
                exit_code = 127

            snippet = redact_secrets(output)[-self.output_limit :]
            result = CheckResult(
                job_id=job_id,
                check_name=name,
                command=command,
                exit_code=exit_code,
                duration_ms=duration_ms,
                output_snippet=snippet,
                candidate_sha=candidate_sha,
                candidate_generation=candidate_generation,
            )
            results.append(result)

            # Classify diagnostic
            if exit_code == 0:
                diag_status = EvidenceDiagnosticStatus.PASS
                reason = "Check passed successfully."
            elif (
                exit_code in (126, 127)
                or "command not found" in snippet.lower()
                or "no such file or directory" in snippet.lower()
            ):
                diag_status = EvidenceDiagnosticStatus.ENVIRONMENT_UNAVAILABLE
                reason = f"Check environment unavailable: {snippet}"
            else:
                diag_status = EvidenceDiagnosticStatus.FAIL
                reason = f"Check failed: {snippet}"

            diag = EvidenceDiagnostic(
                job_id=job_id,
                attempt_id=attempt_id,
                stage_type="CHECKS",
                check_name=name,
                diagnostic_status=diag_status,
                environment_identity=env_identity,
                candidate_sha=candidate_sha,
                reason=reason,
                evidence_reference={"exit_code": exit_code, "command": command},
            )
            diagnostics.append(diag)

        return ChecksRunResult(
            passed=all(result.exit_code == 0 for result in results),
            results=results,
            diagnostics=diagnostics,
        )
