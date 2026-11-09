"""Canonical agent skills and OpenSpec workflows provisioning and readiness verification."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from minime.logging import get_logger

logger = get_logger("services.canonical_capabilities")


def resolve_canonical_source_root() -> Path:
    """Resolve the canonical mini-me repository root containing .agents and .agent directories."""
    candidates = [
        Path(__file__).resolve().parents[3],
        Path(os.environ.get("MINIME_RUNTIME_ROOT", ".")).resolve(),
        Path.cwd().resolve(),
    ]
    for candidate in candidates:
        if (candidate / ".agents" / "skills").is_dir() and (candidate / ".agent" / "workflows").is_dir():
            return candidate
    return Path(__file__).resolve().parents[3]


def provision_canonical_capabilities(
    target_root: Path,
    profiles: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Provision all canonical mini me skills and OpenSpec workflows into target directory."""
    source_root = resolve_canonical_source_root()
    target = target_root.resolve()

    skills_copied: list[str] = []
    workflows_copied: list[str] = []

    # 1. Provision .agents/skills
    source_agents_skills = source_root / ".agents" / "skills"
    if source_agents_skills.is_dir():
        target_agents_skills = target / ".agents" / "skills"
        target_agent_skills = target / ".agent" / "skills"
        target_agents_skills.mkdir(parents=True, exist_ok=True)
        target_agent_skills.mkdir(parents=True, exist_ok=True)

        for item in source_agents_skills.iterdir():
            if item.is_dir() and (item.name.startswith("minime-") or item.name.startswith("openspec-")):
                # Copy into .agents/skills
                dest_agents = target_agents_skills / item.name
                shutil.copytree(item, dest_agents, dirs_exist_ok=True)
                # Copy into .agent/skills as well for multi-harness compatibility
                dest_agent = target_agent_skills / item.name
                shutil.copytree(item, dest_agent, dirs_exist_ok=True)
                skills_copied.append(item.name)

    # 2. Provision .agent/workflows
    source_agent_workflows = source_root / ".agent" / "workflows"
    if source_agent_workflows.is_dir():
        target_agent_workflows = target / ".agent" / "workflows"
        target_agent_workflows.mkdir(parents=True, exist_ok=True)

        for item in source_agent_workflows.iterdir():
            if item.is_file() and (item.name.startswith("opsx-") or item.name.startswith("minime-")):
                dest = target_agent_workflows / item.name
                shutil.copy2(item, dest)
                workflows_copied.append(item.name)

    logger.info(
        f"Provisioned {len(skills_copied)} skills and {len(workflows_copied)} workflows into {target}"
    )

    return {
        "source_root": str(source_root),
        "target_root": str(target),
        "skills_count": len(skills_copied),
        "workflows_count": len(workflows_copied),
        "skills": sorted(set(skills_copied)),
        "workflows": sorted(set(workflows_copied)),
    }


def verify_workflow_readiness(
    target_root: Path,
    profiles: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Verify that required workflow and skill files exist and are readable in target root."""
    target = target_root.resolve()
    missing: list[str] = []

    # Essential mini me skills required across all workflows
    essential_skills = [
        "minime-request-normalizer",
        "minime-pr-preparer",
        "openspec-propose",
        "openspec-apply-change",
        "openspec-verify-change",
    ]
    for skill in essential_skills:
        skill_file = target / ".agents" / "skills" / skill / "SKILL.md"
        if not skill_file.is_file():
            missing.append(f".agents/skills/{skill}/SKILL.md")

    # Essential workflows for Antigravity / AGY
    essential_workflows = [
        "opsx-propose.md",
        "opsx-apply.md",
        "opsx-verify.md",
    ]
    for wf in essential_workflows:
        wf_file = target / ".agent" / "workflows" / wf
        if not wf_file.is_file():
            missing.append(f".agent/workflows/{wf}")

    is_ready = len(missing) == 0
    return is_ready, missing
