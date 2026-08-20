"""DeepSeek Direct auditor runner and prompt construction."""

from __future__ import annotations

import asyncio
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

from minime.domain.models import CheckResult, Project, Review, ReviewFinding
from minime.logging import redact_secrets

DEEPSEEK_DIRECT_ENDPOINT = "https://api.deepseek.com/chat/completions"


@dataclass(frozen=True)
class AuditorResult:
    exit_code: int
    timed_out: bool
    output: list[str]
    duration_ms: int
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    error_message: str | None = None


class AuditorRunnerInterface:
    async def run(
        self, worktree_path: Path, prompt_context: str, timeout_seconds: int
    ) -> AuditorResult:
        raise NotImplementedError


class DeepSeekAuditorRunner(AuditorRunnerInterface):
    """Direct DeepSeek API runner. No OpenRouter or fallback providers are permitted."""

    def __init__(
        self,
        api_key: str | None = None,
        endpoint: str = DEEPSEEK_DIRECT_ENDPOINT,
        model: str = "deepseek-chat",
        client: httpx.AsyncClient | None = None,
    ):
        self.api_key = api_key if api_key is not None else os.getenv("DEEPSEEK_API_KEY")
        self.endpoint = endpoint
        self.model = model
        self.client = client

    def _validate_direct_endpoint(self) -> None:
        parsed = urlparse(self.endpoint)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or host != "api.deepseek.com":
            raise ValueError("DeepSeek audit endpoint must be direct https://api.deepseek.com.")
        if "openrouter" in self.endpoint.lower():
            raise ValueError("DeepSeek audit must not be routed through OpenRouter.")

    async def run(
        self, worktree_path: Path, prompt_context: str, timeout_seconds: int
    ) -> AuditorResult:
        del worktree_path
        self._validate_direct_endpoint()
        if not self.api_key:
            return AuditorResult(
                exit_code=1,
                timed_out=False,
                output=[],
                duration_ms=0,
                provider="deepseek",
                model=self.model,
                error_message="DEEPSEEK_API_KEY is not configured.",
            )

        start = asyncio.get_running_loop().time()
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are DeepSeek Direct acting only as a read-only independent contradiction auditor.",
                },
                {"role": "user", "content": prompt_context},
            ],
            "temperature": 0,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        client = self.client or httpx.AsyncClient(timeout=timeout_seconds)
        should_close = self.client is None
        try:
            response = await client.post(self.endpoint, headers=headers, json=payload)
            duration_ms = int((asyncio.get_running_loop().time() - start) * 1000)
            if response.status_code >= 400:
                return AuditorResult(
                    exit_code=response.status_code,
                    timed_out=False,
                    output=[],
                    duration_ms=duration_ms,
                    provider="deepseek",
                    model=self.model,
                    error_message=redact_secrets(
                        f"DeepSeek API returned HTTP {response.status_code}: {response.text[:500]}",
                        [self.api_key],
                    ),
                )
            try:
                data = response.json()
                content = data["choices"][0]["message"]["content"]
            except Exception as exc:
                return AuditorResult(
                    exit_code=1,
                    timed_out=False,
                    output=[],
                    duration_ms=duration_ms,
                    provider="deepseek",
                    model=self.model,
                    error_message=redact_secrets(
                        f"Invalid DeepSeek response body: {exc}", [self.api_key]
                    ),
                )
            return AuditorResult(
                exit_code=0,
                timed_out=False,
                output=[redact_secrets(str(content), [self.api_key])],
                duration_ms=duration_ms,
                provider="deepseek",
                model=self.model,
            )
        except (httpx.TimeoutException, TimeoutError):
            return AuditorResult(
                exit_code=1,
                timed_out=True,
                output=[],
                duration_ms=int((asyncio.get_running_loop().time() - start) * 1000),
                provider="deepseek",
                model=self.model,
                error_message="DeepSeek API request timed out.",
            )
        except httpx.HTTPError as exc:
            return AuditorResult(
                exit_code=1,
                timed_out=False,
                output=[],
                duration_ms=int((asyncio.get_running_loop().time() - start) * 1000),
                provider="deepseek",
                model=self.model,
                error_message=redact_secrets(f"DeepSeek API request failed: {exc}", [self.api_key]),
            )
        finally:
            if should_close:
                await client.aclose()


class MockAuditorRunner(AuditorRunnerInterface):
    def __init__(
        self,
        exit_code: int = 0,
        output: list[str] | None = None,
        timed_out: bool = False,
        provider: str = "deepseek",
        model: str = "deepseek-chat",
        error_message: str | None = None,
    ):
        self.exit_code = exit_code
        self.output = output or []
        self.timed_out = timed_out
        self.provider = provider
        self.model = model
        self.error_message = error_message

    async def run(
        self, worktree_path: Path, prompt_context: str, timeout_seconds: int
    ) -> AuditorResult:
        del worktree_path, prompt_context, timeout_seconds
        return AuditorResult(
            exit_code=self.exit_code,
            timed_out=self.timed_out,
            output=[redact_secrets(line) for line in self.output],
            duration_ms=1,
            provider=self.provider,
            model=self.model,
            error_message=redact_secrets(self.error_message or ""),
        )


def _git_output(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return f"[git command failed: {' '.join(args)}: {proc.stderr.strip()}]"
    return proc.stdout.strip()


def build_audit_prompt(
    project: Project,
    change_name: str,
    job_id: str,
    audit_id: str,
    candidate_sha: str,
    base_sha: str,
    audit_view_path: Path,
    checks_results: list[CheckResult],
    review: Review,
    review_findings: list[ReviewFinding],
) -> str:
    """Build explicit immutable DeepSeek Direct audit context."""
    change_dir = audit_view_path / project.openspec_path / "changes" / change_name
    specs: list[dict[str, str]] = []
    specs_root = change_dir / "specs"
    if specs_root.exists():
        for spec_file in sorted(specs_root.glob("**/*.md")):
            specs.append(
                {
                    "path": str(spec_file.relative_to(specs_root)),
                    "content": spec_file.read_text(encoding="utf-8"),
                }
            )

    payload = {
        "project_id": project.project_id,
        "repository": project.repository,
        "change_id": change_name,
        "job_id": job_id,
        "audit_id": audit_id,
        "candidate_readonly_view_path": str(audit_view_path),
        "candidate_sha": candidate_sha,
        "base_sha": base_sha,
        "implementer": project.implementer,
        "complementary_reviewer": project.reviewer,
        "review": {
            "review_id": review.review_id,
            "verdict": review.verdict.value if review.verdict else None,
            "candidate_sha": review.candidate_sha,
            "base_sha": review.base_sha,
            "summary": review.summary,
            "findings": [
                {
                    "severity": f.severity.value,
                    "location": f.location,
                    "violated_requirement": f.violated_requirement,
                    "expected_correction": f.expected_correction,
                }
                for f in review_findings
            ],
        },
        "checks": [
            {
                "name": c.check_name,
                "command": c.command,
                "exit_code": c.exit_code,
                "duration_ms": c.duration_ms,
                "output_snippet": c.output_snippet,
            }
            for c in checks_results
        ],
        "git_diff": _git_output(["diff", f"{base_sha}..{candidate_sha}"], audit_view_path),
        "openspec": {
            "proposal": (change_dir / "proposal.md").read_text(encoding="utf-8")
            if (change_dir / "proposal.md").exists()
            else "",
            "design": (change_dir / "design.md").read_text(encoding="utf-8")
            if (change_dir / "design.md").exists()
            else "",
            "tasks": (change_dir / "tasks.md").read_text(encoding="utf-8")
            if (change_dir / "tasks.md").exists()
            else "",
            "specs": specs,
        },
    }

    import json

    schema_instruction = """
You are DeepSeek Direct, an independent read-only contradiction and risk auditor.
You are NOT replacing the Codex/Antigravity complementary reviewer and cannot turn CHANGES_REQUIRED into approval.

Audit only the exact change_id, repository, base_sha, and candidate_sha in the payload. Do not infer latest, active, or newest changes.
Remain read-only: do not edit files, commit, push, merge, change OpenSpec tasks, alter policy, change budgets, or change repository bindings.

Look for missed contract violations, contradictions between evidence and implementation, integrity/security concerns, unsafe assumptions, hidden failure modes, and material risks missed by the complementary review.

Return exactly one JSON object, optionally wrapped in a single markdown json code fence, matching:
{
  "risk": "low" | "medium" | "high" | "critical",
  "summary": "non-empty summary",
  "findings": [
    {
      "severity": "low" | "medium" | "high" | "critical",
      "category": "spec | correctness | security | test | maintainability | repository_binding | other",
      "message": "finding text",
      "file": "optional file path or null",
      "location": "optional location or null"
    }
  ]
}
Do not include extra properties.
"""

    return (
        "### DEEPSEEK DIRECT AUDIT CONTEXT ###\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        f"{schema_instruction.strip()}\n"
    )
