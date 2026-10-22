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


def test_official_init_fails_closed_for_unselected_or_unsupported_agents(tmp_path):
    with pytest.raises(ValueError, match="supports only selected"):
        OpenSpecAdapter().install_official_integrations(Path(tmp_path), ["openrouter"])
