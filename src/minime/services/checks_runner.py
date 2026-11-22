"""Sequential deterministic checks runner."""

from __future__ import annotations

import asyncio
import os
import re
import signal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlsplit

from minime.domain.enums import EvidenceDiagnosticStatus, ExternalOutcome
from minime.domain.models import CheckResult, EvidenceDiagnostic
from minime.domain.models import ProjectTestDatabase
from minime.logging import redact_secrets


@dataclass(frozen=True)
class ChecksRunResult:
    passed: bool
    results: list[CheckResult]
    diagnostics: list[EvidenceDiagnostic] = field(default_factory=list)
    pending_ci_checks: list[dict[str, str]] = field(default_factory=list)


class ChecksRunner:
    def __init__(
        self,
        output_limit: int = 4000,
        timeout_seconds: int = 300,
        runtime_root: str | None = None,
    ):
        self.output_limit = output_limit
        self.timeout_seconds = timeout_seconds
        self.runtime_root = runtime_root

    async def run(
        self,
        job_id: str,
        checks: list[dict],
        worktree_path: str | Path,
        candidate_sha: str = "",
        candidate_generation: int | None = None,
        attempt_id: str | None = None,
        process_start_observer: Callable[[dict], None] | None = None,
        test_database: ProjectTestDatabase | dict | None = None,
        allow_ci_deferral: bool = False,
    ) -> ChecksRunResult:
        results: list[CheckResult] = []
        diagnostics: list[EvidenceDiagnostic] = []
        pending_ci_checks: list[dict[str, str]] = []
        env_identity = str(worktree_path)[-128:]
        ephemeral_caches: list[Path] = []

        try:
            for index, check in enumerate(checks, start=1):
                name = str(check.get("name") or f"check-{index}")
                command = str(check.get("command") or "")
                safe_command = redact_secrets(command)
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
                if re.search(r"\bpostgres(?:ql)?(?:\+[A-Za-z0-9_]+)?://", command, re.IGNORECASE):
                    reason = "Inline PostgreSQL URLs are rejected; configure the project's isolated test database profile."
                    result = CheckResult(
                        job_id=job_id,
                        check_name=name,
                        command=safe_command,
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
                            evidence_reference={"exit_code": 126, "command": safe_command},
                        )
                    )
                    continue

                from minime.services.agent_confinement import (
                    AgentProcessConfinement,
                    safe_prepare_cache_dir,
                    validate_secure_cache_path,
                )

                env = AgentProcessConfinement.prepare_candidate_test_environment()
                database_url: str | None = None

                # Isolate bytecode compilation to a secure, process-private directory outside candidate worktree
                import tempfile

                current_uid = os.getuid()
                pycache_dir: Path | None = None

                # Attempt 1: XDG_CACHE_HOME or ~/.cache/minime/pycache/<job_id>
                candidate_base = os.environ.get("XDG_CACHE_HOME")
                if candidate_base:
                    base_path = Path(candidate_base).expanduser()
                else:
                    base_path = Path.home() / ".cache"

                try:
                    target = base_path / "minime" / "pycache" / job_id
                    pycache_dir = safe_prepare_cache_dir(
                        target, expected_uid=current_uid, job_id=job_id
                    )
                except (OSError, PermissionError):
                    pycache_dir = None

                # Attempt 2: Fallback to securely generated private temporary directory (0700)
                if pycache_dir is None:
                    tmp_dir = tempfile.mkdtemp(prefix=f"minime_cache_{current_uid}_", suffix=f"_{job_id}")
                    os.chmod(tmp_dir, 0o700)
                    target = Path(tmp_dir)
                    pycache_dir = validate_secure_cache_path(
                        target, expected_uid=current_uid, job_id=job_id
                    )
                    if pycache_dir not in ephemeral_caches:
                        ephemeral_caches.append(pycache_dir)

                env["PYTHONPYCACHEPREFIX"] = str(pycache_dir.resolve())
                # Browser runners and other tools may create temporary profiles
                # outside Python's cache path. Keep those files inside the same
                # private location explicitly mounted by process confinement.
                env["TMPDIR"] = str(pycache_dir.resolve())
                env["TMP"] = str(pycache_dir.resolve())
                env["TEMP"] = str(pycache_dir.resolve())

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
                legacy_database_configured = any(
                    key in check for key in ("database_url", "expected_database", "expected_db", "disposable_postgres")
                )
                uses_test_database = check.get("uses_test_database") is True
                if legacy_database_configured or uses_test_database:
                    database_url, database_error = self._resolve_test_database_url(
                        check=check,
                        test_database=test_database,
                        host_environment=os.environ,
                    )
                    if database_error is not None or database_url is None:
                        reason = database_error or "Project test database configuration is invalid."
                        result = CheckResult(
                            job_id=job_id,
                            check_name=name,
                        command=safe_command,
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
                                evidence_reference={"exit_code": 126, "command": safe_command},
                            )
                        )
                        continue
                    validated_profile = ProjectTestDatabase.model_validate(test_database)
                    env[validated_profile.url_env] = database_url
                    env["DATABASE_URL"] = database_url

                cmd_to_run = command
                if "pytest" in command and "-o pythonpath" not in command:
                    cmd_to_run = f'{command} -o pythonpath=". src"'

                start = asyncio.get_running_loop().time()
                proc = None
                try:
                    confinement = AgentProcessConfinement(
                        allowed_worktree_path=str(worktree_path),
                        runtime_root=self.runtime_root,
                    )
                    preflight = confinement.validate_command_preflight(cwd=str(worktree_path))
                    if (
                        not confinement.is_confinement_available()
                        or preflight.outcome != ExternalOutcome.SUCCESS
                    ):
                        reason = f"Check environment unavailable: Process confinement failed: {preflight.error_message if preflight.outcome != ExternalOutcome.SUCCESS else 'Agent process confinement capability unavailable.'}"
                        result = CheckResult(
                            job_id=job_id,
                            check_name=name,
                            command=safe_command,
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
                                diagnostic_status=EvidenceDiagnosticStatus.ENVIRONMENT_UNAVAILABLE,
                                environment_identity=env_identity,
                                candidate_sha=candidate_sha,
                                reason=reason,
                                evidence_reference={"exit_code": 126, "command": safe_command},
                            )
                        )
                        continue

                    wrapped_cmd = confinement.wrap_command(
                        cmd_to_run,
                        secure_cache_path=pycache_dir,
                        job_id=job_id,
                    )
                    proc = await asyncio.create_subprocess_exec(
                        *wrapped_cmd,
                        cwd=str(worktree_path),
                        env=env,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        start_new_session=True,
                    )
                    if process_start_observer is not None:
                        from minime.services.agent_confinement import process_identity

                        identity = process_identity(proc.pid)
                        identity["pgid"] = proc.pid
                        try:
                            process_start_observer(identity)
                        except Exception:
                            try:
                                os.killpg(proc.pid, signal.SIGKILL)
                            except OSError:
                                proc.kill()
                            await proc.communicate()
                            raise
                    stdout, stderr = await asyncio.wait_for(
                        proc.communicate(), timeout=self.timeout_seconds
                    )
                    duration_ms = int((asyncio.get_running_loop().time() - start) * 1000)
                    output = (stdout + stderr).decode(errors="replace")
                    exit_code = proc.returncode or 0
                except asyncio.TimeoutError:
                    duration_ms = int((asyncio.get_running_loop().time() - start) * 1000)
                    if proc and proc.returncode is None:
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                        except OSError:
                            pass
                    output = (
                        f"Environment execution failure: Check timed out after {self.timeout_seconds}s"
                    )
                    exit_code = 124
                except Exception as err:
                    duration_ms = int((asyncio.get_running_loop().time() - start) * 1000)
                    if proc and proc.returncode is None:
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                        except OSError:
                            pass
                    output = f"Environment execution failure: {err}"
                    exit_code = 127
                except BaseException:
                    if proc and proc.returncode is None:
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                        except OSError:
                            pass
                    raise

                snippet = redact_secrets(
                    output,
                    custom_secrets=[database_url] if database_url else None,
                )[-self.output_limit :]
                result = CheckResult(
                    job_id=job_id,
                    check_name=name,
                    command=safe_command,
                    exit_code=exit_code,
                    duration_ms=duration_ms,
                    output_snippet=snippet,
                    candidate_sha=candidate_sha,
                    candidate_generation=candidate_generation,
                )
                # Classify diagnostic
                if exit_code == 0:
                    diag_status = EvidenceDiagnosticStatus.PASS
                    reason = "Check passed successfully."
                elif (
                    exit_code in (126, 127)
                    or "command not found" in snippet.lower()
                    or "no such file or directory" in snippet.lower()
                    or "executable doesn't exist" in snippet.lower()
                    or "executable does not exist" in snippet.lower()
                    or "missing dependencies to run browsers" in snippet.lower()
                    or "failed to launch browser" in snippet.lower()
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
                    evidence_reference={"exit_code": exit_code, "command": safe_command},
                )
                if allow_ci_deferral and self._has_authorized_ci_deferral(
                    check=check,
                    diagnostic_status=diag_status,
                    output=output,
                ):
                    pending_ci_checks.append(
                        {
                            "check_name": name,
                            "pr_ci_check_name": str(check["pr_ci_check_name"]).strip(),
                            "candidate_sha": candidate_sha,
                        }
                    )
                    diag.reason = (
                        f"Check could not run in this stage; awaiting configured project CI check "
                        f"'{str(check['pr_ci_check_name']).strip()}' for candidate {candidate_sha}."
                    )
                    diag.evidence_reference = {
                        "exit_code": exit_code,
                        "command": command,
                        "pr_ci_check_name": str(check["pr_ci_check_name"]).strip(),
                        "candidate_sha": candidate_sha,
                        "status": "PENDING",
                    }
                    diagnostics.append(diag)
                    continue
                results.append(result)
                diagnostics.append(diag)

            # Post-check worktree hygiene: purge any transient untracked runtime artifacts
            from minime.services.candidate_manifest import purge_transient_generated_artifacts

            purge_transient_generated_artifacts(worktree_path)

            return ChecksRunResult(
                passed=(
                    all(result.exit_code == 0 for result in results)
                    and len(results) + len(pending_ci_checks) == len(checks)
                ),
                results=results,
                diagnostics=diagnostics,
                pending_ci_checks=pending_ci_checks,
            )
        finally:
            for c_path in ephemeral_caches:
                if c_path.exists():
                    import shutil

                    shutil.rmtree(c_path, ignore_errors=True)

    @staticmethod
    def _resolve_test_database_url(
        *,
        check: dict,
        test_database: ProjectTestDatabase | dict | None,
        host_environment: dict[str, str],
    ) -> tuple[str | None, str | None]:
        """Resolve a host-only URL reference and verify its exact configured test target."""
        if not isinstance(test_database, (ProjectTestDatabase, dict)):
            return None, "Project test database is not configured; database check rejected before execution."
        if check.get("uses_test_database") is not True or "database_url" in check:
            return None, "Database check must use the configured project test database; inline URLs are rejected."
        try:
            profile = ProjectTestDatabase.model_validate(test_database)
        except Exception:
            return None, "Project test database profile is invalid; database check rejected before execution."
        database_url = host_environment.get(profile.url_env)
        if not isinstance(database_url, str) or not database_url.strip():
            return None, "Configured project test database environment reference is unset."
        try:
            parsed = urlsplit(database_url.strip())
            host = (parsed.hostname or "").lower()
            port = parsed.port or 5432
            database_name = unquote(parsed.path.lstrip("/"))
        except (ValueError, UnicodeError):
            return None, "Configured project test database URL is invalid."
        if parsed.scheme not in {"postgres", "postgresql"} and not parsed.scheme.startswith(
            "postgresql+"
        ):
            return None, "Configured project test database must use PostgreSQL."
        if (
            host != profile.host
            or port != profile.port
            or database_name != profile.database_name
            or database_name.casefold() == "minime"
            or database_name.casefold()
            in {name.casefold() for name in profile.production_database_names}
        ):
            return None, "Configured database target does not match the isolated project test identity."
        return database_url.strip(), None

    @staticmethod
    def _has_authorized_ci_deferral(
        *, check: dict, diagnostic_status: EvidenceDiagnosticStatus, output: str
    ) -> bool:
        """Defer only observable environment-unavailable checks with an explicit CI mapping."""
        check_name = check.get("pr_ci_check_name")
        if not isinstance(check_name, str) or not check_name.strip():
            return False
        if diagnostic_status != EvidenceDiagnosticStatus.ENVIRONMENT_UNAVAILABLE:
            return False
        lowered = output.lower()
        if "process confinement" in lowered or "agent process confinement capability unavailable" in lowered:
            return False
        return any(
            marker in lowered
            for marker in (
                "command not found",
                "no such file or directory",
                "executable doesn't exist",
                "executable does not exist",
                "missing dependencies to run browsers",
                "failed to launch browser",
                "connection refused",
                "could not connect to server",
                "timeout expired",
                "could not translate host name",
            )
        )
