from pathlib import Path

import pytest

from minime.adapters.openspec import OpenSpecAdapter


def test_open_spec_cli_reports_version_and_native_agent_setup_support():
    evidence = OpenSpecAdapter().inspect_cli()

    assert evidence["available"] is True
    assert evidence["version"]
    assert evidence["init_tools_supported"] is True


def test_official_init_installs_complete_codex_and_antigravity_integrations(tmp_path):
    project = tmp_path / "new-project"
    project.mkdir()

    try:
        evidence = OpenSpecAdapter().install_official_integrations(
            project, ["codex", "antigravity"]
        )
    except RuntimeError as exc:
        # Some official CLI profiles advertise Antigravity but do not emit its
        # native workflows. F3 must block rather than emulate that capability.
        assert "complete compatible reference set" in str(exc)
        return

    assert evidence["agents"] == ["antigravity", "codex"]
    assert (project / "openspec/config.yaml").is_file()
    codex_skills = list((project / ".agents/skills").glob("openspec-*/SKILL.md"))
    workflow_root = OpenSpecAdapter._workflow_integration_root(project)
    agy_workflows = list((project / workflow_root).glob("opsx-*.md"))
    assert len(codex_skills) >= 6
    assert len(agy_workflows) >= 6
    codex_names = {path.parent.name.removeprefix("openspec-") for path in codex_skills}
    assert {name.removesuffix("-change").removesuffix("-specs") for name in codex_names} == {
        path.stem.removeprefix("opsx-") for path in agy_workflows
    }
    assert evidence["integrations"]["codex"] == sorted(codex_names)
    assert evidence["integrations"]["antigravity"] == sorted(
        path.stem.removeprefix("opsx-") for path in agy_workflows
    )
    assert OpenSpecAdapter.inspect_integrations(
        project, ["codex", "antigravity"]
    )["complete"] is True


def test_official_init_preserves_existing_project_instructions(tmp_path):
    project = tmp_path / "existing-project"
    (project / "openspec").mkdir(parents=True)
    instructions = "# Project instructions\nKeep this content.\n"
    config = "schema: spec-driven\ncontext: existing-context.md\n"
    (project / "AGENTS.md").write_text(instructions, encoding="utf-8")
    (project / "openspec/config.yaml").write_text(config, encoding="utf-8")
    (project / "existing-context.md").write_text("Approved context.\n", encoding="utf-8")

    try:
        OpenSpecAdapter().install_official_integrations(project, ["codex", "antigravity"])
    except RuntimeError as exc:
        assert "complete compatible reference set" in str(exc)
        assert (project / "AGENTS.md").read_text(encoding="utf-8") == instructions
        assert (project / "openspec/config.yaml").read_text(encoding="utf-8") == config
        assert (project / "existing-context.md").read_text(encoding="utf-8") == "Approved context.\n"
        return

    assert (project / "AGENTS.md").read_text(encoding="utf-8") == instructions
    assert (project / "openspec/config.yaml").read_text(encoding="utf-8") == config
    assert (project / "existing-context.md").read_text(encoding="utf-8") == "Approved context.\n"


def test_official_init_blocks_without_overwriting_customized_integration(tmp_path):
    project = tmp_path / "existing-project"
    skill_path = project / ".agents/skills/openspec-propose/SKILL.md"
    skill_path.parent.mkdir(parents=True)
    custom_skill = "# Existing customized skill\nKeep this content.\n"
    skill_path.write_text(custom_skill, encoding="utf-8")

    with pytest.raises(RuntimeError, match="conflicts with the installed official version"):
        OpenSpecAdapter().install_official_integrations(project, ["codex"])

    assert skill_path.read_text(encoding="utf-8") == custom_skill
    assert not (project / "openspec/config.yaml").exists()


def test_official_init_fails_closed_for_unselected_or_unsupported_agents(tmp_path):
    with pytest.raises(ValueError, match="supports only selected"):
        OpenSpecAdapter().install_official_integrations(Path(tmp_path), ["openrouter"])


def test_official_capability_discovery_uses_only_a_disposable_repository():
    adapter = OpenSpecAdapter()
    evidence = adapter.discover_official_integrations(["codex"])

    assert evidence["version"]
    assert len(evidence["integrations"]["codex"]) >= 6


def test_native_integration_inspection_fails_closed_when_extended_lifecycle_is_missing(tmp_path):
    (tmp_path / ".agents/skills/openspec-propose").mkdir(parents=True)
    (tmp_path / ".agents/skills/openspec-propose/SKILL.md").write_text("name: openspec-propose")
    (tmp_path / "openspec").mkdir()
    (tmp_path / "openspec/config.yaml").write_text("schema: spec-driven\n")

    evidence = OpenSpecAdapter.inspect_integrations(tmp_path, ["codex"])

    assert evidence["complete"] is False
    assert "verify-change" in evidence["required_operations"]["codex"]


def test_official_setup_rejects_symlinked_integration_targets_before_init(tmp_path, monkeypatch):
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    (project / ".agents").symlink_to(outside, target_is_directory=True)
    adapter = OpenSpecAdapter()

    monkeypatch.setattr(
        adapter,
        "inspect_cli",
        lambda: {
            "available": True,
            "version": "test-version",
            "init_tools_supported": True,
            "no_animation_supported": True,
        },
    )
    with pytest.raises(ValueError, match="contains a symlink"):
        adapter.install_official_integrations(project, ["codex"])

    assert list(outside.iterdir()) == []


def test_official_setup_rejects_symlinked_skill_directory_before_init(tmp_path, monkeypatch):
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    skills = project / ".agents/skills"
    skills.mkdir(parents=True)
    (skills / "openspec-propose").symlink_to(outside, target_is_directory=True)
    adapter = OpenSpecAdapter()
    monkeypatch.setattr(
        adapter,
        "inspect_cli",
        lambda: {
            "available": True,
            "version": "test-version",
            "init_tools_supported": True,
            "no_animation_supported": True,
        },
    )

    with pytest.raises(ValueError, match="contains a symlink"):
        adapter.install_official_integrations(project, ["codex"])

    assert list(outside.iterdir()) == []


def test_official_setup_rejects_symlinked_agent_instruction_before_init(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "operator-instructions.md"
    outside.write_text("Do not modify this file.\n", encoding="utf-8")
    (project / "AGENTS.md").symlink_to(outside)
    adapter = OpenSpecAdapter()
    monkeypatch.setattr(
        adapter,
        "inspect_cli",
        lambda: {
            "available": True,
            "version": "test-version",
            "init_tools_supported": True,
            "no_animation_supported": True,
        },
    )

    with pytest.raises(ValueError, match="contains a symlink"):
        adapter.install_official_integrations(project, ["codex"])

    assert outside.read_text(encoding="utf-8") == "Do not modify this file.\n"
