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

    evidence = OpenSpecAdapter().install_official_integrations(
        project, ["codex", "antigravity"]
    )

    assert evidence["agents"] == ["antigravity", "codex"]
    assert (project / "openspec/config.yaml").is_file()
    codex_skills = list((project / ".agents/skills").glob("openspec-*/SKILL.md"))
    agy_workflows = list((project / ".agent/workflows").glob("opsx-*.md"))
    assert len(codex_skills) >= 12
    assert len(agy_workflows) >= 12
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


def test_official_init_fails_closed_for_unselected_or_unsupported_agents(tmp_path):
    with pytest.raises(ValueError, match="supports only selected"):
        OpenSpecAdapter().install_official_integrations(Path(tmp_path), ["openrouter"])


def test_official_capability_discovery_uses_only_a_disposable_repository():
    adapter = OpenSpecAdapter()
    evidence = adapter.discover_official_integrations(["codex"])

    assert evidence["version"]
    assert len(evidence["integrations"]["codex"]) >= 12


def test_native_integration_inspection_fails_closed_when_extended_lifecycle_is_missing(tmp_path):
    (tmp_path / ".agents/skills/openspec-propose").mkdir(parents=True)
    (tmp_path / ".agents/skills/openspec-propose/SKILL.md").write_text("name: openspec-propose")
    (tmp_path / "openspec").mkdir()
    (tmp_path / "openspec/config.yaml").write_text("schema: spec-driven\n")

    evidence = OpenSpecAdapter.inspect_integrations(tmp_path, ["codex"])

    assert evidence["complete"] is False
    assert "verify-change" in evidence["required_operations"]["codex"]
